import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { fetchSettings, updateDataSources } from '../api/client';
import { useConnection } from '../store/connection';

interface AvailableDataProvider {
  id: string;
  name?: string;
  markets?: string[];
  free?: boolean;
  enabled_by_default?: boolean;
  description?: string;
  [key: string]: unknown;
}

interface ProviderCredentialField {
  key: string;
  label?: string;
  secret?: boolean;
  hint?: string;
  [key: string]: unknown;
}

interface DataSourcesConfig {
  providers?: Record<string, unknown>;
  provider_credentials?: Record<string, Record<string, string>>;
  provider_states?: Record<string, { enabled?: boolean }>;
  [key: string]: unknown;
}

export default function DataSourcesScreen() {
  const { baseURL, token } = useConnection();
  const [providers, setProviders] = useState<AvailableDataProvider[]>([]);
  const [schema, setSchema] = useState<Record<string, ProviderCredentialField[]>>({});
  const [config, setConfig] = useState<DataSourcesConfig | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, string>>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const s = await fetchSettings(baseURL, token);
      const provs = (s.available_data_providers as AvailableDataProvider[]) ?? [];
      const sch = (s.provider_credential_schema as Record<string, ProviderCredentialField[]>) ?? {};
      const ds = (s.data_sources as DataSourcesConfig) ?? {};
      setProviders(provs);
      setSchema(sch);
      setConfig(ds);
      const creds = ds.provider_credentials ?? {};
      const d: Record<string, Record<string, string>> = {};
      for (const [pid, fields] of Object.entries(sch)) {
        d[pid] = {};
        for (const f of fields) d[pid][f.key] = creds[pid]?.[f.key] ?? '';
      }
      setDrafts(d);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const isEnabled = (pid: string) =>
    config?.provider_states?.[pid]?.enabled ?? providers.find((p) => p.id === pid)?.enabled_by_default ?? false;

  const toggle = async (pid: string) => {
    if (!config) return;
    const next: DataSourcesConfig = {
      ...config,
      provider_states: { ...(config.provider_states ?? {}), [pid]: { enabled: !isEnabled(pid) } },
    };
    setConfig(next);
    await updateDataSources(baseURL, token, next);
  };

  const saveCreds = async () => {
    if (!config) return;
    setSaving(true);
    setMessage('');
    try {
      const creds = { ...(config.provider_credentials ?? {}) };
      for (const [pid, fields] of Object.entries(drafts)) {
        creds[pid] = { ...(creds[pid] ?? {}), ...fields };
      }
      const next: DataSourcesConfig = { ...config, provider_credentials: creds };
      setConfig(next);
      await updateDataSources(baseURL, token, next);
      setMessage('已保存');
    } catch {
      setMessage('保存失败');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <ActivityIndicator style={{ marginTop: 60 }} />;

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16 }}>
      {providers.map((p) => {
        const fields = schema[p.id] ?? [];
        const enabled = isEnabled(p.id);
        return (
          <View key={p.id} style={styles.card}>
            <View style={styles.head}>
              <View style={{ flex: 1 }}>
                <Text style={styles.name}>
                  {p.name}
                  {p.free ? <Text style={styles.freeTag}> 免费</Text> : <Text style={styles.paidTag}> 需 API</Text>}
                </Text>
                {p.markets ? <Text style={styles.markets}>{(p.markets as string[]).join(' · ')}</Text> : null}
                {p.description ? <Text style={styles.desc} numberOfLines={3}>{p.description}</Text> : null}
              </View>
              <Switch value={enabled} onValueChange={() => void toggle(p.id)} />
            </View>

            {fields.map((f) => (
              <View key={f.key} style={styles.field}>
                <Text style={styles.fieldLabel}>{f.label ?? f.key}</Text>
                <TextInput
                  style={styles.input}
                  value={drafts[p.id]?.[f.key] ?? ''}
                  onChangeText={(t) => setDrafts((d) => ({ ...d, [p.id]: { ...(d[p.id] ?? {}), [f.key]: t } }))}
                  secureTextEntry={!!f.secret}
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder={f.secret ? '••••••' : ''}
                />
                {f.hint ? <Text style={styles.hint}>{f.hint}</Text> : null}
              </View>
            ))}
          </View>
        );
      })}

      {Object.values(drafts).some((d) => Object.values(d).some((v) => v)) ? (
        <Pressable style={styles.saveBtn} onPress={() => void saveCreds()} disabled={saving}>
          <Text style={styles.saveText}>{saving ? '保存中…' : '保存 API 凭证'}</Text>
        </Pressable>
      ) : null}
      {message ? <Text style={styles.message}>{message}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  card: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 14, marginBottom: 12 },
  head: { flexDirection: 'row', alignItems: 'flex-start' },
  name: { fontSize: 15, fontWeight: '700' },
  freeTag: { color: '#26a69a', fontSize: 12 },
  paidTag: { color: '#f59e0b', fontSize: 12 },
  markets: { fontSize: 12, color: '#999', marginTop: 2 },
  desc: { fontSize: 12, color: '#666', marginTop: 6 },
  field: { marginTop: 10 },
  fieldLabel: { fontSize: 12, color: '#666', marginBottom: 4 },
  input: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, fontSize: 14 },
  hint: { fontSize: 11, color: '#aaa', marginTop: 4 },
  saveBtn: { backgroundColor: '#007AFF', borderRadius: 8, padding: 14, alignItems: 'center' },
  saveText: { color: '#fff', fontWeight: '600' },
  message: { textAlign: 'center', color: '#26a69a', marginTop: 8 },
});
