import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { fetchSettings, updateNotificationPrefs } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { SettingsGroup, SettingsNote, SettingsRow, SettingsSwitchRow } from '../components/SettingsList';
import { relativeTime } from '../lib/format';
import { useThemedStyles, useTokens } from '../lib/tokens';
import { useConnection } from '../store/connection';
import { usePush } from '../store/push';

export default function PushSettingsScreen() {
  const t = useTokens();
  const styles = useThemedStyles(baseStyles);
  const { baseURL, token } = useConnection();
  const push = usePush();

  const [dutyPush, setDutyPush] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSettings(baseURL, token);
      setDutyPush(!!s.notification_prefs?.duty_completion_push);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleDuty = async (v: boolean) => {
    const before = dutyPush;
    setDutyPush(v); // 乐观更新
    try {
      await updateNotificationPrefs(baseURL, token, { duty_completion_push: v });
    } catch (e) {
      setDutyPush(before); // 失败回滚
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  return (
    <ScrollView style={[styles.container, { backgroundColor: t.pageBg }]} contentContainerStyle={styles.content}>
      <SettingsGroup title="本机推送" footer="自托管方案：App 前台每分钟检查一次；退到后台由系统任务约每 15 分钟检查一次。">
        <SettingsSwitchRow
          label="事件与回复推送"
          hint="盯盘事件（high/medium）与会话回复完成时通知"
          value={push.enabled}
          disabled={push.busy}
          onChange={(v) => void (v ? push.enable() : push.disable())}
          last
        />
      </SettingsGroup>

      <SettingsGroup title="状态">
        <SettingsRow label="通知权限" value={push.granted ? '已授权' : '未授权'} />
        <SettingsRow label="后台检查" value={push.backgroundRegistered ? '已注册' : '未注册'} />
        <SettingsRow
          label="上次检查"
          value={push.lastCheckAt ? relativeTime(new Date(push.lastCheckAt).toISOString()) : '—'}
          last
        />
      </SettingsGroup>

      <View style={styles.actions}>
        <Pressable style={[styles.btn, { backgroundColor: t.accent }, push.busy && styles.disabled]} onPress={() => void push.test()} disabled={push.busy}>
          <Text style={styles.btnText}>发送测试通知</Text>
        </Pressable>
        <Pressable style={[styles.btnGhost, { borderColor: t.accent }]} onPress={() => void push.checkNow()} disabled={push.busy}>
          <Text style={[styles.btnGhostText, { color: t.accent }]}>立即检查</Text>
        </Pressable>
      </View>
      {push.message ? <Text style={[styles.message, { color: t.sub }]}>{push.message}</Text> : null}

      <SettingsGroup title="服务端推送偏好" footer="失败始终推送；完成通知受此开关控制。需服务端配置推送通道后真机才能收到远程推送。">
        <SettingsSwitchRow
          label="定时任务完成通知"
          hint="定时值班 / 发现任务跑完时通知"
          value={dutyPush}
          onChange={(v) => void toggleDuty(v)}
          last
        />
      </SettingsGroup>

      <SettingsGroup>
        <SettingsNote>
          点通知会跳到对应页面（盯盘事件 → 事件详情；回复完成 → 对话页）。
        </SettingsNote>
      </SettingsGroup>
    </ScrollView>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1 },
  content: { paddingTop: 20, paddingBottom: 40 },
  actions: { flexDirection: 'row', gap: 10, paddingHorizontal: 16, marginBottom: 8 },
  btn: { flex: 1, borderRadius: 12, paddingVertical: 13, alignItems: 'center' },
  disabled: { opacity: 0.6 },
  btnText: { color: '#fff', fontWeight: '600', fontSize: 14.5 },
  btnGhost: { flex: 1, borderWidth: 1, borderRadius: 12, paddingVertical: 13, alignItems: 'center' },
  btnGhostText: { fontWeight: '600', fontSize: 14.5 },
  message: { textAlign: 'center', fontSize: 12.5, marginTop: 8, marginBottom: 20, paddingHorizontal: 24 },
});
