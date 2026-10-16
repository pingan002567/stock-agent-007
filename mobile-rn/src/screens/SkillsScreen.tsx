import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, View } from 'react-native';
import { fetchSettings, setSkillEnabled } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { SettingsGroup, SettingsSwitchRow } from '../components/SettingsList';
import { useTokens } from '../lib/tokens';
import { useConnection } from '../store/connection';
import type { SkillInfo } from '../types';

export default function SkillsScreen() {
  const t = useTokens();
  const { baseURL, token } = useConnection();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSettings(baseURL, token);
      setSkills(s.skills ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = async (name: string, enabled: boolean) => {
    const before = skills;
    setSkills((prev) => prev.map((k) => (k.name === name ? { ...k, enabled } : k))); // 乐观更新
    try {
      await setSkillEnabled(baseURL, token, name, enabled);
    } catch (e) {
      setSkills(before); // 失败回滚（对齐 iOS）
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  const enabled = skills.filter((s) => s.enabled).length;

  return (
    <ScrollView style={[styles.container, { backgroundColor: t.pageBg }]} contentContainerStyle={styles.content}>
      <SettingsGroup
        title={`已启用 ${enabled}/${skills.length}`}
        footer="技能决定 Agent 会用到哪些分析能力；带锁的技能由服务端策略控制，无法在此改动。"
      >
        {skills.map((k, i) => (
          <SettingsSwitchRow
            key={k.name}
            label={String(k.name)}
            hint={k.description ? String(k.description) : undefined}
            value={!!k.enabled}
            disabled={!!k.locked}
            onChange={(v) => void toggle(String(k.name), v)}
            last={i === skills.length - 1}
          />
        ))}
        {skills.length === 0 ? (
          <View style={styles.empty}>
            <SettingsSwitchRow label="暂无技能" value={false} onChange={() => {}} last />
          </View>
        ) : null}
      </SettingsGroup>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  content: { paddingTop: 20, paddingBottom: 40 },
  empty: { opacity: 0.5 },
});
