import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { connectLlmProvider, fetchLlmProviders, setDefaultLlmModel } from '../api/client';
import { ErrorState } from '../components/ErrorState';
import { useConnection } from '../store/connection';
import type { LlmProviderInfo, LlmProvidersSnapshot } from '../types';
import { useThemedStyles } from '../lib/tokens';

/** 模型服务（对齐 iOS SettingsConfigViews 的模型服务页） */
export default function ModelServiceScreen() {
  const styles = useThemedStyles(baseStyles);
  const { baseURL, token } = useConnection();
  const [snap, setSnap] = useState<LlmProvidersSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [keyFor, setKeyFor] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSnap(await fetchLlmProviders(baseURL, token));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [baseURL, token]);

  useEffect(() => {
    void load();
  }, [load]);

  const setDefault = async (providerId: string, modelId: string, modelName?: string) => {
    setBusy(`${providerId}/${modelId}`);
    setMessage('');
    try {
      setSnap(await setDefaultLlmModel(baseURL, token, `${providerId}/${modelId}`));
      setMessage(`已设为默认：${modelName ?? modelId}`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const connect = async (provider: LlmProviderInfo) => {
    const pid = provider.id ?? provider.provider_id ?? '';
    if (!pid) return;
    setBusy(pid);
    setMessage('');
    try {
      setSnap(await connectLlmProvider(baseURL, token, pid, apiKey || undefined));
      setKeyFor(null);
      setApiKey('');
      setMessage(`已连接：${provider.name ?? pid}`);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const confirmDisconnect = (provider: LlmProviderInfo) => {
    const pid = provider.id ?? provider.provider_id ?? '';
    Alert.alert('断开模型服务', `确定断开「${provider.name ?? pid}」？`, [
      { text: '取消', style: 'cancel' },
      { text: '断开', style: 'destructive', onPress: () => void connect({ ...provider, connected: false }) },
    ]);
  };

  if (error) return <ErrorState message={error} onRetry={() => void load()} />;
  if (loading) return <ActivityIndicator style={{ marginTop: 40 }} />;

  const current = snap?.default_model;
  const connected = snap?.connected ?? [];
  const others = [...(snap?.popular ?? []), ...(snap?.catalog ?? [])].filter(
    (p) => !connected.some((c) => (c.id ?? c.provider_id) === (p.id ?? p.provider_id))
  );

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.section}>当前默认</Text>
      <View style={styles.card}>
        <Text style={styles.defaultModel}>{current ?? '未设置'}</Text>
      </View>

      {message ? <Text style={styles.message}>{message}</Text> : null}

      <Text style={styles.section}>已连接</Text>
      {connected.length === 0 ? <Text style={styles.muted}>暂无已连接的服务</Text> : null}
      {connected.map((p) => {
        const pid = p.id ?? p.provider_id ?? '';
        return (
          <View key={pid} style={styles.card}>
            <View style={styles.providerHead}>
              <Text style={styles.providerName}>{p.name ?? pid}</Text>
              <Pressable onPress={() => confirmDisconnect(p)} hitSlop={6}>
                <Text style={styles.danger}>断开</Text>
              </Pressable>
            </View>
            {(p.models ?? []).map((m) => {
              const isDefault = current === `${pid}/${m.id}`;
              return (
                <Pressable
                  key={m.id}
                  style={styles.modelRow}
                  onPress={() => void setDefault(pid, m.id, m.name)}
                  disabled={busy != null}
                >
                  <Text style={styles.modelName}>
                    {isDefault ? '✓ ' : ''}
                    {m.name ?? m.id}
                  </Text>
                  {busy === `${pid}/${m.id}` ? <ActivityIndicator size="small" /> : null}
                </Pressable>
              );
            })}
          </View>
        );
      })}

      <Text style={styles.section}>可接入</Text>
      {others.map((p) => {
        const pid = p.id ?? p.provider_id ?? '';
        return (
          <View key={pid} style={styles.card}>
            <View style={styles.providerHead}>
              <Text style={styles.providerName}>{p.name ?? pid}</Text>
              <Pressable onPress={() => setKeyFor(keyFor === pid ? null : pid)} hitSlop={6}>
                <Text style={styles.link}>{keyFor === pid ? '取消' : '连接'}</Text>
              </Pressable>
            </View>
            {keyFor === pid ? (
              <View style={styles.keyRow}>
                <TextInput
                  style={styles.keyInput}
                  placeholder="API Key"
                  value={apiKey}
                  onChangeText={setApiKey}
                  autoCapitalize="none"
                  secureTextEntry
                />
                <Pressable style={styles.connectBtn} onPress={() => void connect(p)} disabled={busy != null}>
                  {busy === pid ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.connectText}>确定</Text>}
                </Pressable>
              </View>
            ) : null}
          </View>
        );
      })}
    </ScrollView>
  );
}

const baseStyles = StyleSheet.create({
  container: { padding: 16 },
  section: { fontSize: 13, color: '#8E8E93', marginTop: 12, marginBottom: 8 },
  card: { backgroundColor: '#f7f8fa', borderRadius: 10, padding: 12, marginBottom: 10 },
  defaultModel: { fontSize: 15, fontWeight: '600' },
  message: { color: '#007AFF', fontSize: 13, marginTop: 8 },
  muted: { color: '#999', fontSize: 13 },
  providerHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  providerName: { fontSize: 15, fontWeight: '600' },
  link: { color: '#007AFF', fontSize: 13 },
  danger: { color: '#FF3B30', fontSize: 13 },
  modelRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e3e5e8',
    marginTop: 6,
  },
  modelName: { fontSize: 14 },
  keyRow: { flexDirection: 'row', marginTop: 10 },
  keyInput: { flex: 1, borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, fontSize: 14 },
  connectBtn: {
    marginLeft: 8,
    backgroundColor: '#007AFF',
    borderRadius: 6,
    paddingHorizontal: 16,
    justifyContent: 'center',
  },
  connectText: { color: '#fff', fontWeight: '600' },
});
