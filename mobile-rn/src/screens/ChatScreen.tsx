import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { listUploads, uploadFiles } from '../api/client';
import { AssistantBubble } from '../components/AssistantBubble';
import { SessionDrawer } from '../components/SessionDrawer';
import { useChat } from '../store/chat';
import { useConnection } from '../store/connection';
import { usePrefill } from '../store/prefill';
import type { SessionUpload, Turn } from '../types';

export default function ChatScreen() {
  const { disconnect } = useConnection();
  const chat = useChat();
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [input, setInput] = useState('');
  const [pendingUploads, setPendingUploads] = useState<SessionUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const listRef = useRef<FlatList<Turn>>(null);

  useEffect(() => {
    void chat.loadSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const pre = usePrefill.getState().take();
    if (pre) setInput(pre);
  }, []);

  const currentTitle = chat.sessions.find((s) => s.session_id === chat.currentSessionId)?.title ?? '对话';

  const pickAndUpload = async () => {
    const res = await DocumentPicker.getDocumentAsync({ multiple: true, copyToCacheDirectory: true });
    if (res.canceled) return;
    const files = res.assets.map((a) => ({ uri: a.uri, name: a.name, mimeType: a.mimeType ?? 'application/octet-stream' }));
    setUploading(true);
    try {
      let sid = chat.currentSessionId;
      if (!sid) {
        await chat.newSession();
        sid = useChat.getState().currentSessionId;
      }
      if (!sid) return;
      const { baseURL, token } = useConnection.getState();
      await uploadFiles(baseURL, token, sid, files);
      const list = await listUploads(baseURL, token, sid);
      setPendingUploads(list.files ?? []);
    } catch (e) {
      // 附件上传失败不阻塞对话
    } finally {
      setUploading(false);
    }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || chat.busy) return;
    setInput('');
    const uploads = pendingUploads;
    setPendingUploads([]);
    await chat.send(text, uploads);
  };

  const renderTurn = ({ item }: { item: Turn }) => (
    <View style={styles.turn}>
      <View style={styles.userRow}>
        <View style={styles.userBubble}>
          <Text style={styles.userText}>{item.userText}</Text>
        </View>
      </View>
      {item.assistant ? (
        <View style={styles.assistantRow}>
          <AssistantBubble
            assistant={item.assistant}
            onRetry={() => void chat.retryLast()}
            onReplyClarification={(resp) => void chat.replyClarification(resp)}
          />
        </View>
      ) : null}
    </View>
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
    >
      <View style={styles.header}>
        <Pressable onPress={() => setDrawerVisible(true)} hitSlop={8}>
          <Text style={styles.menu}>☰</Text>
        </Pressable>
        <Text style={styles.headerTitle} numberOfLines={1}>
          {currentTitle}
        </Text>
        <Pressable onPress={disconnect} hitSlop={8}>
          <Text style={styles.disconnect}>断开</Text>
        </Pressable>
      </View>

      <FlatList
        ref={listRef}
        data={chat.turns}
        keyExtractor={(t) => t.id}
        renderItem={renderTurn}
        contentContainerStyle={styles.listContent}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
        ListHeaderComponent={
          chat.hasMore ? (
            <Pressable style={styles.loadEarlier} onPress={() => void chat.loadEarlier()}>
              {chat.loadingMore ? <ActivityIndicator size="small" /> : <Text style={styles.loadEarlierText}>加载更早的消息</Text>}
            </Pressable>
          ) : null
        }
        ListEmptyComponent={
          chat.loadingHistory ? (
            <ActivityIndicator style={{ marginTop: 40 }} />
          ) : (
            <Text style={styles.empty}>发送一条消息开始对话</Text>
          )
        }
      />

      {pendingUploads.length > 0 ? (
        <View style={styles.uploadStrip}>
          {pendingUploads.map((u) => (
            <View key={u.filename} style={styles.uploadChip}>
              <Text style={styles.uploadChipText}>{u.filename}</Text>
            </View>
          ))}
        </View>
      ) : null}

      <View style={styles.composer}>
        <Pressable style={styles.attachBtn} onPress={() => void pickAndUpload()} disabled={uploading}>
          {uploading ? <ActivityIndicator size="small" /> : <Text style={styles.attachText}>＋</Text>}
        </Pressable>
        <TextInput
          style={styles.input}
          value={input}
          onChangeText={setInput}
          placeholder="输入消息"
          multiline
        />
        {chat.busy ? (
          <Pressable style={styles.sendBtn} onPress={chat.stop}>
            <Text style={styles.sendText}>停止</Text>
          </Pressable>
        ) : (
          <Pressable style={[styles.sendBtn, !input.trim() && styles.sendDisabled]} onPress={() => void send()} disabled={!input.trim()}>
            <Text style={styles.sendText}>发送</Text>
          </Pressable>
        )}
      </View>

      <SessionDrawer
        visible={drawerVisible}
        onClose={() => setDrawerVisible(false)}
        sessions={chat.sessions}
        currentSessionId={chat.currentSessionId}
        onNew={() => {
          void chat.newSession();
          setDrawerVisible(false);
        }}
        onOpen={(id) => {
          void chat.openSession(id);
          setDrawerVisible(false);
        }}
        onRename={(id, title) => void chat.renameSession(id, title)}
        onDelete={(id) => void chat.removeSession(id)}
      />
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  menu: { fontSize: 20, color: '#007AFF', marginRight: 12 },
  headerTitle: { flex: 1, fontSize: 16, fontWeight: '600', textAlign: 'center' },
  disconnect: { color: '#007AFF', fontSize: 14 },
  listContent: { padding: 16, flexGrow: 1 },
  turn: { marginBottom: 16 },
  userRow: { alignItems: 'flex-end', marginBottom: 6 },
  userBubble: { backgroundColor: '#007AFF', borderRadius: 12, padding: 10, maxWidth: '85%' },
  userText: { color: '#fff', fontSize: 15, lineHeight: 21 },
  assistantRow: { alignItems: 'flex-start' },
  loadEarlier: { alignSelf: 'center', paddingVertical: 10 },
  loadEarlierText: { color: '#007AFF', fontSize: 13 },
  empty: { textAlign: 'center', color: '#999', marginTop: 40 },
  uploadStrip: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, paddingHorizontal: 16, paddingBottom: 4 },
  uploadChip: { backgroundColor: '#eef3f8', borderRadius: 12, paddingHorizontal: 10, paddingVertical: 4 },
  uploadChipText: { fontSize: 12, color: '#334' },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: 8,
    borderTopWidth: 1,
    borderTopColor: '#eee',
  },
  attachBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: '#ccc',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 6,
  },
  attachText: { fontSize: 18, color: '#666' },
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
  sendDisabled: { opacity: 0.4 },
  sendText: { color: '#fff', fontWeight: '600' },
});
