import { useEffect, useState } from 'react';
import { ActivityIndicator, Alert, FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { relativeTime } from '../lib/format';
import type { CopilotSession } from '../types';
import { useThemedStyles } from '../lib/tokens';

interface Props {
  visible: boolean;
  onClose: () => void;
  sessions: CopilotSession[];
  currentSessionId: string | null;
  activeStreams: Record<string, string>;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

export function SessionDrawer({
  visible,
  onClose,
  sessions,
  currentSessionId,
  activeStreams,
  onNew,
  onOpen,
  onRename,
  onDelete,
}: Props) {
  const styles = useThemedStyles(baseStyles);
  const [query, setQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  // 打开抽屉的那一次触摸可能穿透到遮罩，导致刚展开就被关掉
  const [ready, setReady] = useState(false);
  const [renameValue, setRenameValue] = useState('');

  useEffect(() => {
    if (!visible) {
      setReady(false);
      return;
    }
    const t = setTimeout(() => setReady(true), 350);
    return () => clearTimeout(t);
  }, [visible]);

  const q = query.trim().toLowerCase();
  const filtered = sessions.filter((s) => (s.title ?? '').toLowerCase().includes(q) || s.session_id.toLowerCase().includes(q));

  const beginRename = (s: CopilotSession) => {
    setEditingId(s.session_id);
    setRenameValue(s.title ?? '');
  };
  const commitRename = () => {
    if (editingId && renameValue.trim()) onRename(editingId, renameValue.trim());
    setEditingId(null);
  };

  const confirmDelete = (s: CopilotSession) => {
    Alert.alert('删除对话', `确定删除「${s.title || '新对话'}」？`, [
      { text: '取消', style: 'cancel' },
      { text: '删除', style: 'destructive', onPress: () => onDelete(s.session_id) },
    ]);
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent>
      <View style={styles.root}>
        {/* 点击上方空白处收起会话列表 */}
        <Pressable style={styles.backdrop} onPress={() => ready && onClose()} />
        <View style={styles.sheet}>
          <View style={styles.header}>
            <Text style={styles.title}>对话</Text>
            <Pressable style={styles.newBtn} onPress={onNew}>
              <Text style={styles.newText}>＋ 新建</Text>
            </Pressable>
            <Pressable onPress={onClose}>
              <Text style={styles.close}>关闭</Text>
            </Pressable>
          </View>

          <TextInput
            style={styles.search}
            placeholder="搜索标题或会话 ID"
            value={query}
            onChangeText={setQuery}
            autoCapitalize="none"
          />

          <FlatList
            data={filtered}
            keyExtractor={(s) => s.session_id}
            renderItem={({ item }) => (
              <View style={[styles.item, item.session_id === currentSessionId && styles.itemActive]}>
                {editingId === item.session_id ? (
                  <View style={styles.editRow}>
                    <TextInput
                      style={styles.editInput}
                      value={renameValue}
                      onChangeText={setRenameValue}
                      autoFocus
                      onSubmitEditing={commitRename}
                    />
                    <Pressable onPress={commitRename}>
                      <Text style={styles.link}>保存</Text>
                    </Pressable>
                  </View>
                ) : (
                  <Pressable style={styles.itemBody} onPress={() => onOpen(item.session_id)}>
                    <View style={styles.titleRow}>
                      <Text style={styles.itemTitle} numberOfLines={1}>
                        {item.title || '新对话'}
                      </Text>
                      {activeStreams[item.session_id] ? <ActivityIndicator size="small" style={{ marginLeft: 6 }} /> : null}
                    </View>
                    <Text style={styles.itemMeta}>
                      {relativeTime(item.last_message_at ?? item.created_at)} · {item.message_count ?? 0} 条
                    </Text>
                  </Pressable>
                )}

                {editingId !== item.session_id && (
                  <View style={styles.actions}>
                    <Pressable onPress={() => beginRename(item)} hitSlop={8}>
                      <Text style={styles.link}>重命名</Text>
                    </Pressable>
                    <Pressable onPress={() => confirmDelete(item)} hitSlop={8}>
                      <Text style={styles.delete}>删除</Text>
                    </Pressable>
                  </View>
                )}
              </View>
            )}
            ListEmptyComponent={<Text style={styles.empty}>暂无对话</Text>}
          />
        </View>
      </View>
    </Modal>
  );
}

const baseStyles = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  // 与弹层同级、铺满整屏；点它（即弹层上方的空白）收起
  backdrop: { ...{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 }, backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { backgroundColor: '#fff', borderTopLeftRadius: 16, borderTopRightRadius: 16, height: '85%', padding: 16 },
  header: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  title: { fontSize: 18, fontWeight: '700', flex: 1 },
  newBtn: { marginRight: 16 },
  newText: { color: '#007AFF', fontSize: 15 },
  close: { color: '#666', fontSize: 15 },
  search: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, marginBottom: 12, fontSize: 14 },
  item: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#eee',
    paddingVertical: 12,
    flexDirection: 'row',
    alignItems: 'center',
  },
  itemActive: { backgroundColor: '#f0f6ff' },
  itemBody: { flex: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'center' },
  itemTitle: { fontSize: 15, fontWeight: '500', flexShrink: 1 },
  itemMeta: { fontSize: 12, color: '#999', marginTop: 2 },
  actions: { flexDirection: 'row', gap: 12, marginLeft: 8 },
  link: { color: '#007AFF', fontSize: 13 },
  delete: { color: '#c0392b', fontSize: 13 },
  editRow: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 },
  editInput: { flex: 1, borderWidth: 1, borderColor: '#007AFF', borderRadius: 6, padding: 6, fontSize: 14 },
  empty: { textAlign: 'center', color: '#999', marginTop: 40 },
});
