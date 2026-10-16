import { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import * as ImagePicker from 'expo-image-picker';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import {
  fetchCostSummary,
  fetchSettings,
  setSkillEnabled,
  updateInvestorProfile,
  updateMarketRefresh,
  updateNotificationPrefs,
} from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { relativeTime } from '../lib/format';
import { usePush } from '../store/push';
import type { RootStackParamList } from '../navigation';
import { useAppearance } from '../store/appearance';
import { useConnection } from '../store/connection';
import { ACCENT_PRESETS, useTheme } from '../store/theme';
import type { CostSummary, WorkbenchSettings } from '../types';
import { useThemedStyles } from '../lib/tokens';

type Nav = NativeStackNavigationProp<RootStackParamList>;

const PAGE_RANGE: [number, number] = [30, 600];
const WARMUP_RANGE: [number, number] = [120, 3600];
const COOLDOWN_RANGE: [number, number] = [30, 1800];

export default function SettingsScreen() {
  const styles = useThemedStyles(baseStyles);
  const navigation = useNavigation<Nav>();
  const insets = useSafeAreaInsets();
  const { baseURL, token, health, reprobeHealth } = useConnection();
  const { accentHex, scheme, setAccent, setScheme } = useTheme();
  const push = usePush();
  const backgroundUri = useAppearance((s) => s.backgroundUri);
  const dim = useAppearance((s) => s.dim);

  const [settings, setSettings] = useState<WorkbenchSettings | null>(null);
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [probeResult, setProbeResult] = useState<string | null>(null);

  const [pageSec, setPageSec] = useState(30);
  const [warmupSec, setWarmupSec] = useState(300);
  const [cooldownSec, setCooldownSec] = useState(120);
  const [risk, setRisk] = useState('moderate');
  const [notes, setNotes] = useState('');
  const [customHex, setCustomHex] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, c] = await Promise.all([fetchSettings(baseURL, token), fetchCostSummary(baseURL, token)]);
      setSettings(s);
      setCost(c);
      const mr = s.market_refresh;
      setPageSec(Number(mr?.page_refresh_seconds ?? 30));
      setWarmupSec(Number(mr?.warmup_seconds ?? 300));
      setCooldownSec(Number(mr?.manual_cooldown_seconds ?? 120));
      setRisk(String(s.investor_profile?.risk_level ?? 'moderate'));
      setNotes(String(s.investor_profile?.notes ?? ''));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const runtime = settings?.agent_runtime;
  const skills = settings?.skills ?? [];
  const costDays = cost?.days ?? [];
  const totalCost = cost?.total?.total_cost ?? 0;

  const flash = (m: string) => {
    setMessage(m);
    setTimeout(() => setMessage(''), 2000);
  };

  const toggleSkill = async (name: string, enabled: boolean) => {
    const before = settings;
    setSettings((s) => (s ? { ...s, skills: s.skills?.map((k) => (k.name === name ? { ...k, enabled } : k)) } : s));
    try {
      await setSkillEnabled(baseURL, token, name, enabled);
    } catch (e) {
      setSettings(before); // 失败回滚（对齐 iOS optimistic revert）
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const saveMarketRefresh = async () => {
    try {
      await updateMarketRefresh(baseURL, token, {
        page_refresh_seconds: clamp(pageSec, PAGE_RANGE),
        warmup_seconds: clamp(warmupSec, WARMUP_RANGE),
        manual_cooldown_seconds: clamp(cooldownSec, COOLDOWN_RANGE),
      });
      flash('已保存刷新频率');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const saveProfile = async () => {
    try {
      await updateInvestorProfile(baseURL, token, { risk_level: risk, notes });
      flash('已保存投资者画像');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const toggleNotify = async (v: boolean) => {
    const before = settings?.notification_prefs?.duty_completion_push;
    setSettings((s) => (s ? { ...s, notification_prefs: { ...s.notification_prefs, duty_completion_push: v } } : s));
    try {
      await updateNotificationPrefs(baseURL, token, { duty_completion_push: v });
    } catch (e) {
      setSettings((s) => (s ? { ...s, notification_prefs: { ...s.notification_prefs, duty_completion_push: before } } : s));
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const applyCustomHex = () => {
    const v = customHex.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) {
      setAccent(v.toUpperCase());
      setCustomHex('');
      flash('已应用自定义主题色');
    } else {
      flash('请输入 #RRGGBB 格式');
    }
  };

  const pickWallpaper = async () => {
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.9 });
    if (res.canceled || !res.assets?.[0]) return;
    useAppearance.getState().setBackground(res.assets[0].uri);
    flash('背景已更新');
  };

  if (loading && !settings) return <ActivityIndicator style={{ marginTop: 60 }} />;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={{ padding: 16, paddingTop: insets.top + 16 }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
    >
      <Text style={styles.title}>设置</Text>

      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}
      {message ? <Text style={styles.message}>{message}</Text> : null}

      {/* 当前连接 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>当前连接</Text>
        <Text style={styles.line}>地址：{baseURL || '—'}</Text>
        <Text style={styles.line}>令牌：{token ? '已配置' : '未配置'}</Text>
        <Text style={styles.line}>健康：{health?.status ?? '—'}</Text>
        <Pressable
          style={styles.saveBtn}
          onPress={() => void reprobeHealth().then((r) => setProbeResult(r ?? '正常'))}
        >
          <Text style={styles.saveText}>重新探测健康</Text>
        </Pressable>
        {probeResult ? <Text style={styles.line}>结果：{probeResult}</Text> : null}
      </View>

      {runtime?.degraded ? (
        <View style={styles.degraded}>
          <Text style={styles.degradedText}>⚠️ 运行降级：{String(runtime.degraded_reason ?? '原因未知')}</Text>
        </View>
      ) : null}

      {/* 后端与模型 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>后端与模型</Text>
        <Pressable onPress={() => navigation.navigate('Runtime')} style={styles.navRow}>
          <Text style={styles.link}>运行状态 ›</Text>
        </Pressable>
        <Pressable onPress={() => navigation.navigate('ModelService')} style={styles.navRow}>
          <Text style={styles.link}>模型服务 ›</Text>
        </Pressable>
      </View>

      {/* AI 技能 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>AI 技能</Text>
        {skills.length === 0 ? <Text style={styles.muted}>暂无技能</Text> : null}
        {skills.map((k) => (
          <View key={k.name} style={styles.skillRow}>
            <View style={styles.skillBody}>
              <Text style={styles.toggleLabel}>{k.name}</Text>
              {k.description ? <Text style={styles.skillDesc}>{String(k.description)}</Text> : null}
            </View>
            <Switch value={!!k.enabled} disabled={!!k.locked} onValueChange={(v) => void toggleSkill(String(k.name), v)} />
          </View>
        ))}
      </View>

      {/* 费用 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>用量与费用（累计 ¥{Number(totalCost).toFixed(4)}）</Text>
        {costDays.length === 0 ? <Text style={styles.muted}>暂无用量</Text> : null}
        {costDays.slice(-7).map((d) => (
          <Text key={d.date} style={styles.line}>
            {d.date} · ¥{Number(d.total_cost ?? 0).toFixed(4)} · in {d.total_input_tokens ?? 0} / out {d.total_output_tokens ?? 0} · {d.run_count ?? 0} 次
          </Text>
        ))}
      </View>

      {/* 行情 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>行情刷新</Text>
        <View style={styles.presetRow}>
          {[30, 60, 120].map((p) => (
            <Pressable key={p} style={[styles.presetBtn, pageSec === p && styles.presetActive]} onPress={() => setPageSec(p)}>
              <Text style={[styles.presetText, pageSec === p && styles.presetTextActive]}>{p}s</Text>
            </Pressable>
          ))}
        </View>
        <Stepper label="页面刷新" value={pageSec} range={PAGE_RANGE} step={10} onChange={setPageSec} />
        <Stepper label="预热时长" value={warmupSec} range={WARMUP_RANGE} step={30} onChange={setWarmupSec} />
        <Stepper label="手动冷却" value={cooldownSec} range={COOLDOWN_RANGE} step={10} onChange={setCooldownSec} />
        <Pressable style={styles.saveBtn} onPress={() => void saveMarketRefresh()}>
          <Text style={styles.saveText}>保存刷新频率</Text>
        </Pressable>
        <Pressable onPress={() => navigation.navigate('DataSources')} style={styles.navRow}>
          <Text style={styles.link}>行情数据源 ›</Text>
        </Pressable>
      </View>

      {/* 外观与主题 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>外观与主题</Text>
        <View style={styles.accentRow}>
          {ACCENT_PRESETS.map((p) => (
            <Pressable key={p.id} onPress={() => setAccent(p.hex)}>
              <View style={[styles.swatch, { backgroundColor: p.hex }, accentHex === p.hex && styles.swatchActive]}>
                {accentHex === p.hex ? <Text style={styles.checkmark}>✓</Text> : null}
              </View>
            </Pressable>
          ))}
        </View>
        <Text style={styles.muted}>当前 {accentHex}</Text>
        <View style={styles.hexRow}>
          <TextInput
            style={styles.hexInput}
            placeholder="#RRGGBB 自定义"
            value={customHex}
            onChangeText={setCustomHex}
            autoCapitalize="characters"
            autoCorrect={false}
          />
          <Pressable style={styles.hexBtn} onPress={applyCustomHex}>
            <Text style={styles.saveText}>应用</Text>
          </Pressable>
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

        <View style={styles.wallRow}>
          <Pressable style={styles.schemeBtn} onPress={() => void pickWallpaper()}>
            <Text style={styles.schemeText}>{backgroundUri ? '更换背景图' : '选择背景图'}</Text>
          </Pressable>
          {backgroundUri ? (
            <Pressable style={styles.schemeBtn} onPress={() => useAppearance.getState().clearBackground()}>
              <Text style={styles.danger}>清除</Text>
            </Pressable>
          ) : null}
        </View>
        {backgroundUri ? (
          <View style={styles.dimRow}>
            <Text style={styles.line}>遮罩浓度 {Math.round(dim * 100)}%</Text>
            <View style={styles.dimBtns}>
              <Pressable style={styles.dimBtn} onPress={() => useAppearance.getState().setDim(dim - 0.05)}>
                <Text style={styles.dimText}>－</Text>
              </Pressable>
              <Pressable style={styles.dimBtn} onPress={() => useAppearance.getState().setDim(dim + 0.05)}>
                <Text style={styles.dimText}>＋</Text>
              </Pressable>
            </View>
          </View>
        ) : null}
      </View>

      {/* 投资者画像 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>投资者画像</Text>
        {[
          { id: 'conservative', label: '保守', hint: '偏防御、质量与低波动' },
          { id: 'moderate', label: '普通', hint: '轮动主线与中等弹性' },
          { id: 'aggressive', label: '激进', hint: '主题催化与高弹性' },
        ].map((r) => (
          <Pressable key={r.id} style={styles.riskRowItem} onPress={() => setRisk(r.id)}>
            <Text style={styles.radio}>{risk === r.id ? '●' : '○'}</Text>
            <View style={{ flex: 1 }}>
              <Text style={styles.toggleLabel}>{r.label}</Text>
              <Text style={styles.skillDesc}>{r.hint}</Text>
            </View>
          </Pressable>
        ))}
        <TextInput style={styles.input} placeholder="备注" value={notes} onChangeText={setNotes} multiline />
        <Pressable style={styles.saveBtn} onPress={() => void saveProfile()}>
          <Text style={styles.saveText}>保存画像</Text>
        </Pressable>
      </View>

      {/* 通知 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>通知</Text>
        <View style={styles.toggleRow}>
          <Text style={styles.toggleLabel}>定时任务完成推送</Text>
          <Switch value={!!settings?.notification_prefs?.duty_completion_push} onValueChange={(v) => void toggleNotify(v)} />
        </View>
        <Text style={styles.skillDesc}>完成通知默认开启；失败始终推送。需服务端配置推送通道后真机才能收到。</Text>
      </View>

      {/* 推送（自托管：本地通知 + 后台轮询，不依赖第三方） */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>推送</Text>
        <View style={styles.toggleRow}>
          <Text style={styles.toggleLabel}>事件与回复推送</Text>
          <Switch
            value={push.enabled}
            disabled={push.busy}
            onValueChange={(v) => void (v ? push.enable() : push.disable())}
          />
        </View>
        <Text style={styles.line}>通知权限：{push.granted ? '已授权' : '未授权'}</Text>
        <Text style={styles.line}>
          后台检查：{push.backgroundRegistered ? '已注册（约 15 分钟一次）' : '未注册'}
        </Text>
        {push.lastCheckAt ? (
          <Text style={styles.line}>上次检查：{relativeTime(new Date(push.lastCheckAt).toISOString())}</Text>
        ) : null}
        <View style={styles.wallRow}>
          <Pressable style={styles.schemeBtn} onPress={() => void push.test()} disabled={push.busy}>
            <Text style={styles.schemeText}>发送测试通知</Text>
          </Pressable>
          <Pressable style={styles.schemeBtn} onPress={() => void push.checkNow()} disabled={push.busy}>
            <Text style={styles.schemeText}>立即检查</Text>
          </Pressable>
        </View>
        {push.message ? <Text style={styles.message}>{push.message}</Text> : null}
        <Text style={styles.skillDesc}>
          自托管推送：不依赖 FCM / 个推等第三方。App 在前台时每分钟检查一次；退到后台由系统任务约每 15 分钟检查一次。
          会话回复完成也会推送（App 退到后台、JS 被系统回收时靠后台任务补推）。只有 high/medium 级盯盘事件会推送，点通知跳到对应页面。
        </Text>
      </View>

      {/* 功能入口 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>功能</Text>
        <Pressable onPress={() => navigation.navigate('ScheduledTasks')} style={styles.navRow}>
          <Text style={styles.link}>定时值班 ›</Text>
        </Pressable>
        <Pressable onPress={() => navigation.navigate('Reports')} style={styles.navRow}>
          <Text style={styles.link}>研究报告 ›</Text>
        </Pressable>
        <Pressable onPress={() => navigation.navigate('Strategy')} style={styles.navRow}>
          <Text style={styles.link}>策略回测 ›</Text>
        </Pressable>
      </View>

      {/* 交易约束 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>交易约束</Text>
        <Text style={styles.line}>本客户端不下单。所有结论仅供研究参考，不构成投资建议。</Text>
      </View>

      {/* 关于 */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>关于</Text>
        <Text style={styles.line}>客户端：Stock Agent（Android / React Native）</Text>
        <Text style={styles.line}>版本：0.1.0</Text>
        <Text style={styles.line}>包名：com.stockagent.app</Text>
      </View>

      <Pressable style={styles.disconnectBtn} onPress={() => useConnection.getState().disconnect()}>
        <Text style={styles.disconnectText}>切换后端</Text>
      </Pressable>
      <Text style={styles.skillDesc}>返回连接页。已保存的地址和令牌会留在输入框，但仍需再点一次连接。</Text>
    </ScrollView>
  );
}

function clamp(v: number, [min, max]: [number, number]): number {
  return Math.min(max, Math.max(min, v));
}

function Stepper({
  label,
  value,
  range,
  step,
  onChange,
}: {
  label: string;
  value: number;
  range: [number, number];
  step: number;
  onChange: (v: number) => void;
}) {
  const styles = useThemedStyles(baseStyles);
  return (
    <View style={styles.stepperRow}>
      <Text style={styles.toggleLabel}>{label}</Text>
      <View style={styles.dimBtns}>
        <Pressable style={styles.dimBtn} onPress={() => onChange(clamp(value - step, range))}>
          <Text style={styles.dimText}>－</Text>
        </Pressable>
        <Text style={styles.stepperValue}>{value}</Text>
        <Pressable style={styles.dimBtn} onPress={() => onChange(clamp(value + step, range))}>
          <Text style={styles.dimText}>＋</Text>
        </Pressable>
      </View>
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  title: { fontSize: 20, fontWeight: '700', marginBottom: 12 },
  card: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 14, marginBottom: 12 },
  cardTitle: { fontSize: 14, fontWeight: '700', marginBottom: 8 },
  line: { fontSize: 13, color: '#444', marginBottom: 4 },
  message: { color: '#34C759', fontSize: 13, marginBottom: 8 },
  muted: { fontSize: 12, color: '#8E8E93', marginTop: 4 },
  skillDesc: { fontSize: 11, color: '#8E8E93', marginTop: 2, lineHeight: 16 },
  degraded: { backgroundColor: '#FFF4E5', borderRadius: 10, padding: 12, marginBottom: 12 },
  degradedText: { color: '#B26A00', fontSize: 13 },
  toggleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 4 },
  skillRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 6 },
  skillBody: { flex: 1, paddingRight: 12 },
  toggleLabel: { fontSize: 13 },
  link: { color: '#007AFF', fontSize: 14, paddingVertical: 8 },
  navRow: { paddingVertical: 2 },
  input: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, fontSize: 14, marginTop: 10 },
  saveBtn: { backgroundColor: '#007AFF', borderRadius: 8, padding: 10, alignItems: 'center', marginTop: 10 },
  saveText: { color: '#fff', fontWeight: '600' },
  presetRow: { flexDirection: 'row', gap: 8, marginBottom: 8 },
  presetBtn: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: '#ddd' },
  presetActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  presetText: { color: '#666', fontSize: 13 },
  presetTextActive: { color: '#007AFF' },
  stepperRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 6 },
  stepperValue: { minWidth: 52, textAlign: 'center', fontSize: 13 },
  accentRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginBottom: 6 },
  swatch: { width: 32, height: 32, borderRadius: 16, borderWidth: 2, borderColor: 'transparent', alignItems: 'center', justifyContent: 'center' },
  swatchActive: { borderColor: '#333' },
  checkmark: { color: '#fff', fontSize: 15, fontWeight: '700' },
  hexRow: { flexDirection: 'row', marginTop: 10, gap: 8 },
  hexInput: { flex: 1, borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 8, fontSize: 13 },
  hexBtn: { backgroundColor: '#007AFF', borderRadius: 8, paddingHorizontal: 16, justifyContent: 'center' },
  schemeRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  schemeBtn: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: '#ddd' },
  schemeActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  schemeText: { color: '#666', fontSize: 13 },
  schemeTextActive: { color: '#007AFF' },
  wallRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  dimRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 },
  dimBtns: { flexDirection: 'row', alignItems: 'center' },
  dimBtn: { borderWidth: 1, borderColor: '#ccc', borderRadius: 6, paddingHorizontal: 12, paddingVertical: 4 },
  dimText: { fontSize: 14, color: '#333' },
  riskRowItem: { flexDirection: 'row', alignItems: 'center', paddingVertical: 8, gap: 10 },
  radio: { fontSize: 16, color: '#007AFF' },
  danger: { color: '#c0392b', fontSize: 13 },
  disconnectBtn: { marginTop: 4, padding: 14, borderRadius: 10, borderWidth: 1, borderColor: '#c0392b', alignItems: 'center' },
  disconnectText: { color: '#c0392b', fontWeight: '600' },
});
