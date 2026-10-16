import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { ALT_BASE_URL, DEFAULT_BASE_URL, useConnection } from '../store/connection';
import { useThemedStyles } from '../lib/tokens';

export default function ConnectScreen() {
  const styles = useThemedStyles(baseStyles);
  const insets = useSafeAreaInsets();
  const { baseURL, token, status, error, health, connect, lastSuccessfulUrl } = useConnection();
  const [url, setUrl] = useState(baseURL);
  const [tok, setTok] = useState(token);
  const [copied, setCopied] = useState(false);

  // hydrate() 是异步的：它把已保存的地址/令牌写回 store 后，必须同步到输入框
  useEffect(() => {
    if (baseURL) setUrl(baseURL);
    if (token) setTok(token);
  }, [baseURL, token]);

  const quick: { label: string; url: string }[] = [];
  const last = lastSuccessfulUrl.trim();
  if (last && last !== DEFAULT_BASE_URL && last !== ALT_BASE_URL) quick.push({ label: '上次成功', url: last });
  if (DEFAULT_BASE_URL) quick.push({ label: '推荐', url: DEFAULT_BASE_URL });
  if (ALT_BASE_URL) quick.push({ label: '备用', url: ALT_BASE_URL });

  const diagnostics = `URL: ${url}
上次成功: ${last || '—'}
错误: ${error ?? '—'}
时间: ${new Date().toISOString()}`;

  const copyDiagnostics = async () => {
    await Clipboard.setStringAsync(diagnostics);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <ScrollView contentContainerStyle={[styles.container, { paddingTop: insets.top + 20 }]} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>连接后端</Text>
      <Text style={styles.hint}>填写 HTTPS 服务地址和访问令牌。只有点连接后，App 才会访问后端。</Text>

      <Text style={styles.label}>远端地址</Text>
      <TextInput
        style={styles.input}
        value={url}
        onChangeText={setUrl}
        placeholder="https://你的服务器地址"
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
      />

      {quick.length > 0 ? (
        <View style={styles.quickRow}>
          {quick.map((q) => (
            <Pressable key={q.url} style={styles.quickChip} onPress={() => setUrl(q.url)}>
              <Text style={styles.quickText}>{q.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      <Text style={styles.label}>访问令牌</Text>
      <TextInput
        style={styles.input}
        value={tok}
        onChangeText={setTok}
        placeholder="X-Workbench-Token"
        autoCapitalize="none"
        autoCorrect={false}
        secureTextEntry
      />

      {error ? (
        <View style={styles.errorBox}>
          <Text style={styles.error} selectable>
            {error}
          </Text>
          <Pressable onPress={() => void copyDiagnostics()}>
            <Text style={styles.link}>{copied ? '✓ 已复制' : '复制诊断信息'}</Text>
          </Pressable>
        </View>
      ) : null}

      <Pressable
        style={[styles.button, status === 'connecting' && styles.buttonDisabled]}
        disabled={status === 'connecting'}
        onPress={() => void connect(url, tok)}
      >
        <Text style={styles.buttonText}>{status === 'connecting' ? '连接中…' : '连接'}</Text>
      </Pressable>

      {health ? (
        <Text style={styles.health}>
          已连接 · {health.status} · {health.agent_runtime ? 'agent_runtime 正常' : '缺少 agent_runtime'}
        </Text>
      ) : null}
    </ScrollView>
  );
}

const baseStyles = StyleSheet.create({
  container: { padding: 20, paddingTop: 20 },
  title: { fontSize: 24, fontWeight: '700', marginBottom: 6 },
  hint: { fontSize: 13, color: '#8E8E93', marginBottom: 18, lineHeight: 19 },
  label: { fontSize: 13, color: '#666', marginBottom: 6, marginTop: 6 },
  input: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 12, fontSize: 15, marginBottom: 8 },
  quickRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginBottom: 10 },
  quickChip: { borderWidth: 1, borderColor: '#007AFF', borderRadius: 14, paddingHorizontal: 12, paddingVertical: 5 },
  quickText: { color: '#007AFF', fontSize: 12 },
  errorBox: { marginTop: 6, marginBottom: 6 },
  error: { color: '#FF3B30', fontSize: 13, lineHeight: 19 },
  link: { color: '#007AFF', fontSize: 13, marginTop: 6 },
  button: { backgroundColor: '#007AFF', borderRadius: 8, padding: 14, alignItems: 'center', marginTop: 16 },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  health: { marginTop: 14, fontSize: 12, color: '#34C759' },
});
