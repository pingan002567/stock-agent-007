import { useCallback, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { createSession, sendMessage, streamURL } from '../api/client';
import { parseStreamEvent } from '../api/parse';
import { streamSSE } from '../api/sse';
import { useConnection } from '../store/connection';

export default function ChatScreen() {
  const { baseURL, token, disconnect } = useConnection();
  const [input, setInput] = useState('');
  const [answer, setAnswer] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const run = useCallback(async () => {
    const msg = input.trim();
    if (!msg || busy) return;
    setBusy(true);
    setErr(null);
    setAnswer('');
    setInput('');
    try {
      const session = await createSession(baseURL, token);
      const runInfo = await sendMessage(baseURL, token, session.session_id, msg);

      const controller = new AbortController();
      abortRef.current = controller;

      await streamSSE(streamURL(baseURL, token, session.session_id, runInfo.run_id), {
        signal: controller.signal,
        onEvent: (ev) => {
          const u = parseStreamEvent(ev);
          if (u.kind === 'partial') setAnswer((a) => a + u.text);
          else if (u.kind === 'final') setAnswer((a) => (u.text ? u.text : a));
        },
        onError: (e) => setErr(e instanceof Error ? e.message : String(e)),
        onDone: () => setBusy(false),
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      abortRef.current = null;
    }
  }, [baseURL, token, input, busy]);

  const stop = () => {
    abortRef.current?.abort();
    setBusy(false);
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.headerText}>对话</Text>
        <Pressable onPress={disconnect}>
          <Text style={styles.disconnect}>断开</Text>
        </Pressable>
      </View>

      <ScrollView style={styles.body} contentContainerStyle={styles.bodyContent}>
        <Text style={styles.answer}>{answer || '发送一条消息开始…'}</Text>
      </ScrollView>

      {err ? <Text style={styles.error}>{err}</Text> : null}

      <View style={styles.composer}>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder="输入消息"
          multiline
        />
        {busy ? (
          <Pressable style={styles.sendBtn} onPress={stop}>
            <Text style={styles.sendText}>停止</Text>
          </Pressable>
        ) : (
          <Pressable style={styles.sendBtn} onPress={run}>
            <Text style={styles.sendText}>发送</Text>
          </Pressable>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  headerText: { fontSize: 17, fontWeight: '600' },
  disconnect: { color: '#007AFF', fontSize: 15 },
  body: { flex: 1 },
  bodyContent: { padding: 16 },
  answer: { fontSize: 15, lineHeight: 22 },
  error: { color: '#c0392b', paddingHorizontal: 16, paddingVertical: 6 },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: 8,
    borderTopWidth: 1,
    borderTopColor: '#eee',
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: '#ccc',
    borderRadius: 8,
    padding: 10,
    fontSize: 15,
    maxHeight: 120,
  },
  sendBtn: {
    backgroundColor: '#007AFF',
    borderRadius: 8,
    paddingHorizontal: 18,
    paddingVertical: 12,
    marginLeft: 8,
  },
  sendText: { color: '#fff', fontWeight: '600' },
});
