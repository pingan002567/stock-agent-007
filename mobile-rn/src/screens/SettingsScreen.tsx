import { useCallback, useEffect, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { fetchCostSummary, fetchScheduledTasks, fetchSettings } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { SettingsGroup, SettingsNote, SettingsRow } from '../components/SettingsList';
import { useTokens } from '../lib/tokens';
import type { RootStackParamList } from '../navigation';
import { useConnection } from '../store/connection';
import { usePush } from '../store/push';
import { useTheme } from '../store/theme';
import type { CostSummary, ScheduledTask, WorkbenchSettings } from '../types';

type Nav = NativeStackNavigationProp<RootStackParamList>;

const RISK_LABEL: Record<string, string> = {
  conservative: '保守',
  moderate: '普通',
  aggressive: '激进',
};
const SCHEME_LABEL: Record<string, string> = {
  system: '跟随系统',
  light: '浅色',
  dark: '深色',
};

export default function SettingsScreen() {
  const t = useTokens();
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<Nav>();
  const { baseURL, token, health, reprobeHealth, disconnect } = useConnection();
  const scheme = useTheme((s) => s.scheme);
  const push = usePush();

  const [settings, setSettings] = useState<WorkbenchSettings | null>(null);
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [probeMsg, setProbeMsg] = useState<string | null>(null);
  /** 定时任务数：概览里「N 个启用」用；拉不到就显示「—」，不编造 0 */
  const [taskCount, setTaskCount] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, c, tasks] = await Promise.all([
        fetchSettings(baseURL, token),
        fetchCostSummary(baseURL, token),
        fetchScheduledTasks(baseURL, token).catch(() => null),
      ]);
      setSettings(s);
      setCost(c);
      setTaskCount(tasks ? tasks.filter((x: ScheduledTask) => x.enabled !== false).length : null);
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
  const enabledSkills = skills.filter((s) => s.enabled).length;
  const costDays = (cost?.days ?? []).slice(-3).reverse();
  const totalCost = Number(cost?.total?.total_cost ?? 0);
  const risk = String(settings?.investor_profile?.risk_level ?? 'moderate');
  const pageSec = Number(settings?.market_refresh?.page_refresh_seconds ?? 30);

  // 概览派生：能算的才算，算不出来显示「—」
  const providerStates = (settings?.data_sources as { provider_states?: Record<string, { enabled?: boolean }> } | undefined)?.provider_states ?? {};
  const dataTotal = Object.keys(providerStates).length;
  const dataOn = Object.values(providerStates).filter((v) => v?.enabled).length;
  const activePolicy = (settings?.risk_policy as { active?: { name?: string; rules?: Record<string, unknown> } } | undefined)?.active;
  const policyName = activePolicy?.name ?? '默认档';
  const cryptoCapRaw = activePolicy?.rules?.crypto_max_weight_pct;
  const cryptoCap = typeof cryptoCapRaw === 'number' ? cryptoCapRaw : null;
  const singleCapRaw = activePolicy?.rules?.single_position_max_weight_pct;

  /** 待确认项：只列会阻塞使用或明显不合理的，且都能一键跳到对应屏 */
  const pending: { key: string; title: string; action: string; route: string }[] = [];
  if (!runtime?.available) {
    pending.push({ key: 'model', title: '模型未连接', action: '去配置', route: 'ModelService' });
  } else if (runtime?.degraded) {
    pending.push({ key: 'degraded', title: '运行降级', action: '看详情', route: 'Runtime' });
  }
  if (dataOn === 0 && dataTotal > 0) {
    pending.push({ key: 'data', title: '没有启用数据源', action: '去启用', route: 'DataSources' });
  }
  if (typeof singleCapRaw === 'number' && singleCapRaw >= 50) {
    pending.push({
      key: 'risk',
      title: `风控很激进（单票 ${singleCapRaw}%）`,
      action: '看一眼',
      route: 'InvestorProfile',
    });
  }

  return (
    <ScrollView
      style={[styles.container, { backgroundColor: t.pageBg }]}
      contentContainerStyle={[styles.content, { paddingTop: insets.top + 20 }]}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
    >
      {error ? <ErrorState message={error} onRetry={() => void load()} /> : null}

      <SettingsGroup title="连接">
        <SettingsRow label="地址" value={baseURL || '—'} />
        <SettingsRow label="令牌" value={token ? '已配置' : '未配置'} />
        <SettingsRow label="健康" value={health?.status ?? '—'} />
        <SettingsRow
          label="重新探测健康"
          value={probeMsg ?? undefined}
          last
          onPress={() => {
            setProbeMsg('探测中…');
            void reprobeHealth().then((r) => setProbeMsg(r ?? '正常'));
          }}
        />
      </SettingsGroup>

      {runtime?.degraded ? (
        <SettingsGroup title="运行降级">
          <SettingsNote>⚠️ {String(runtime.degraded_reason ?? '原因未知')}</SettingsNote>
        </SettingsGroup>
      ) : null}

      {/* 配置概览：手机上一眼看清「还差什么 / 现在生效什么」，对应 Web 设置首页 */}
      <SettingsGroup title="配置概览">
        <SettingsRow
          icon={runtime?.available ? 'checkmark-circle-outline' : 'alert-circle-outline'}
          label="模型"
          value={runtime?.available ? String(runtime?.model_name ?? '已连接') : '未连接'}
          onPress={() => navigation.navigate('ModelService')}
        />
        <SettingsRow
          icon="server-outline"
          label="数据源"
          value={`${dataOn}/${dataTotal} 启用`}
          onPress={() => navigation.navigate('DataSources')}
        />
        <SettingsRow
          icon="shield-checkmark-outline"
          label="风控"
          value={`${policyName} · 加密 ${cryptoCap == null ? '—' : `${cryptoCap}%`}`}
          onPress={() => navigation.navigate('InvestorProfile')}
        />
        <SettingsRow
          icon="alarm-outline"
          label="定时任务"
          value={taskCount == null ? '—' : `${taskCount} 个启用`}
          last
          onPress={() => navigation.navigate('ScheduledTasks')}
        />
      </SettingsGroup>

      {pending.length > 0 ? (
        <SettingsGroup title="待确认">
          {pending.map((p, i) => (
            <SettingsRow
              key={p.key}
              label={p.title}
              value={p.action}
              last={i === pending.length - 1}
              onPress={() => navigation.navigate(p.route as never)}
            />
          ))}
        </SettingsGroup>
      ) : null}

      <SettingsGroup title="运行与模型">
        <SettingsRow
          icon="speedometer-outline"
          label="运行状态"
          value={String(runtime?.model_name ?? '')}
          onPress={() => navigation.navigate('Runtime')}
        />
        <SettingsRow
          icon="sparkles-outline"
          label="模型服务"
          onPress={() => navigation.navigate('ModelService')}
        />
        <SettingsRow
          icon="extension-puzzle-outline"
          label="AI 技能"
          value={`${enabledSkills}/${skills.length} 已启用`}
          onPress={() => navigation.navigate('Skills')}
        />
        <SettingsRow icon="cash-outline" label="用量与费用" value={`¥${totalCost.toFixed(2)}`} last />
      </SettingsGroup>

      {costDays.length > 0 ? (
        <SettingsGroup title="近几日用量">
          {costDays.map((d, i) => (
            <SettingsRow
              key={String(d.date)}
              label={String(d.date ?? '—')}
              value={`¥${Number(d.total_cost ?? 0).toFixed(4)} · ${d.run_count ?? 0} 次`}
              last={i === costDays.length - 1}
            />
          ))}
        </SettingsGroup>
      ) : null}

      <SettingsGroup title="外观">
        <SettingsRow
          icon="color-palette-outline"
          label="外观与主题"
          value={SCHEME_LABEL[scheme] ?? scheme}
          last
          onPress={() => navigation.navigate('Appearance')}
        />
      </SettingsGroup>

      <SettingsGroup title="行情与数据">
        <SettingsRow
          icon="refresh-outline"
          label="刷新频率"
          value={`${pageSec} 秒`}
          onPress={() => navigation.navigate('MarketRefresh')}
        />
        <SettingsRow
          icon="server-outline"
          label="行情数据源"
          onPress={() => navigation.navigate('DataSources')}
          last
        />
      </SettingsGroup>

      <SettingsGroup title="投研">
        <SettingsRow
          icon="person-outline"
          label="投资者画像"
          value={RISK_LABEL[risk] ?? risk}
          onPress={() => navigation.navigate('InvestorProfile')}
        />
        <SettingsRow icon="calendar-outline" label="定时值班" onPress={() => navigation.navigate('ScheduledTasks')} />
        <SettingsRow icon="document-text-outline" label="研究报告" onPress={() => navigation.navigate('Reports')} />
        <SettingsRow icon="analytics-outline" label="策略回测" onPress={() => navigation.navigate('Strategy')} last />
      </SettingsGroup>

      <SettingsGroup title="通知与推送">
        <SettingsRow
          icon="notifications-outline"
          label="推送设置"
          value={push.enabled ? '已开启' : '未开启'}
          last
          onPress={() => navigation.navigate('PushSettings')}
        />
      </SettingsGroup>

      <SettingsGroup title="交易约束" footer="本客户端不下单。所有结论仅供研究参考，不构成投资建议。">
        <SettingsNote>A 股 / 港股 / 美股行情与研报仅作研究用途，不构成任何投资建议。</SettingsNote>
      </SettingsGroup>

      <SettingsGroup title="关于">
        <SettingsRow label="客户端" value="Android · React Native" />
        <SettingsRow label="版本" value="0.1.0" />
        <SettingsRow label="包名" value="com.stockagent.app" last />
      </SettingsGroup>

      <View style={styles.actions}>
        <Pressable style={[styles.disconnectBtn, { borderColor: t.danger }]} onPress={disconnect}>
          <Text style={[styles.disconnectText, { color: t.danger }]}>切换后端</Text>
        </Pressable>
        <Text style={[styles.hint, { color: t.sub }]}>
          返回连接页；已保存的地址和令牌会留在输入框，仍需再点一次连接。
        </Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { paddingBottom: 40 },
  actions: { paddingHorizontal: 16, marginTop: 4 },
  disconnectBtn: { borderWidth: 1, borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  disconnectText: { fontWeight: '600', fontSize: 15 },
  hint: { fontSize: 11.5, lineHeight: 17, marginTop: 10, marginHorizontal: 8 },
});
