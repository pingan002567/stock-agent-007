import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { useConnection } from '../store/connection';

export default function ConnectScreen() {
  const { baseURL, token, status, error, health, connect } = useConnection();
  const [url, setUrl] = useState(baseURL);
  const [tok, setTok] = useState(token);

  return (
    <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
      <Text style={styles.title}>连接后端</Text>

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

      <Pressable
        style={[styles.button, status === 'connecting' && styles.buttonDisabled]}
        disabled={status === 'connecting'}
        onPress={() => connect(url, tok)}
      >
        <Text style={styles.buttonText}>{status === 'connecting' ? '连接中…' : '连接'}</Text>
      </Pressable>

      {error ? <Text style={styles.error}>{error}</Text> : null}
      {health ? (
        <View style={styles.health}>
          <Text style={styles.healthTitle}>已连接</Text>
          <Text style={styles.healthLine}>模型：{health.agent_runtime?.model_name ?? '-'}</Text>
          <Text style={styles.healthLine}>模式：{health.agent_runtime?.mode ?? '-'}</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 20 },
  title: { fontSize: 24, fontWeight: '600', marginBottom: 20 },
  label: { fontSize: 14, color: '#666', marginTop: 12, marginBottom: 6 },
  input: {
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 12,
    fontSize: 15,
  },
  button: {
    backgroundColor: '#007AFF',
    borderRadius: 8,
    padding: 14,
    alignItems: 'center',
    marginTop: 24,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  error: { color: '#c0392b', marginTop: 12 },
  health: { marginTop: 20, padding: 14, backgroundColor: '#f0f4f8', borderRadius: 8 },
  healthTitle: { fontSize: 15, fontWeight: '600', marginBottom: 6 },
  healthLine: { fontSize: 13, color: '#444' },
});
