import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { fetchSettings } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { useConnection } from '../store/connection';
import { useThemedStyles } from '../lib/tokens';

/** 运行状态（对齐 iOS SettingsExtras.RuntimeSettingsView） */
export default function RuntimeScreen() {
  const styles = useThemedStyles(baseStyles);
  const { baseURL, token } = useConnection();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSettings(baseURL, token);
      setData((s.agent_runtime as Record<string, unknown>) ?? {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (loading) return <ActivityIndicator style={{ marginTop: 40 }} />;

  const entries = Object.entries(data ?? {});
  return (
    <ScrollView
      contentContainerStyle={styles.container}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={() => void load()} />}
    >
      <Text style={styles.section}>Agent Runtime</Text>
      <View style={styles.card}>
        {entries.length === 0 ? (
          <Text style={styles.muted}>暂无运行信息</Text>
        ) : (
          entries.map(([k, v]) => (
            <View key={k} style={styles.row}>
              <Text style={styles.key}>{k}</Text>
              <Text style={styles.value} selectable>
                {typeof v === 'object' ? JSON.stringify(v) : String(v)}
              </Text>
            </View>
          ))
        )}
      </View>
    </ScrollView>
  );
}

const baseStyles = StyleSheet.create({
  container: { padding: 16 },
  section: { fontSize: 13, color: '#8E8E93', marginBottom: 8 },
  card: { backgroundColor: '#f7f8fa', borderRadius: 10, padding: 12 },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6, gap: 12 },
  key: { color: '#555', fontSize: 13, flexShrink: 0 },
  value: { color: '#111', fontSize: 13, flex: 1, textAlign: 'right' },
  muted: { color: '#999', fontSize: 13 },
});
