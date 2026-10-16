import { useState } from 'react';
import { FlatList, Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import type { CopilotSession } from '../types';

interface Props {
  visible: boolean;
  onClose: () => void;
  sessions: CopilotSession[];
  currentSessionId: string | null;
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
  onNew,
  onOpen,
  onRename,
  onDelete,
}: Props) {
  const [query, setQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');

  const filtered = sessions.filter((s) => (s.title ?? '').toLowerCase().includes(query.toLowerCase()));

  const beginRename = (s: CopilotSession) => {
    setEditingId(s.session_id);
    setRenameValue(s.title ?? '');
  };
  const commitRename = () => {
    if (editingId && renameValue.trim()) onRename(editingId, renameValue.trim());
    setEditingId(null);
  };

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} transparent>
      <View style={styles.backdrop}>
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
            placeholder="搜索对话"
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
                    <Text style={styles.itemTitle} numberOfLines={1}>
                      {item.title || '新对话'}
                    </Text>
                    <Text style={styles.itemMeta}>{item.message_count ?? 0} 条消息</Text>
                  </Pressable>
                )}

                {editingId !== item.session_id && (
                  <View style={styles.actions}>
                    <Pressable onPress={() => beginRename(item)} hitSlop={8}>
                      <Text style={styles.link}>重命名</Text>
                    </Pressable>
                    <Pressable onPress={() => onDelete(item.session_id)} hitSlop={8}>
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

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.3)', justifyContent: 'flex-end' },
  sheet: { backgroundColor: '#fff', borderTopLeftRadius: 16, borderTopRightRadius: 16, height: '85%', padding: 16 },
  header: { flexDirection: 'row', alignItems: 'center', marginBottom: 12 },
  title: { fontSize: 18, fontWeight: '700', flex: 1 },
  newBtn: { marginRight: 16 },
  newText: { color: '#007AFF', fontSize: 15 },
  close: { color: '#666', fontSize: 15 },
  search: { borderWidth: 1, borderColor: '#ddd', borderRadius: 8, padding: 10, marginBottom: 12, fontSize: 14 },
  item: { borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#eee', paddingVertical: 12, flexDirection: 'row', alignItems: 'center' },
  itemActive: { backgroundColor: '#f0f6ff' },
  itemBody: { flex: 1 },
  itemTitle: { fontSize: 15, fontWeight: '500' },
  itemMeta: { fontSize: 12, color: '#999', marginTop: 2 },
  actions: { flexDirection: 'row', gap: 12, marginLeft: 8 },
  link: { color: '#007AFF', fontSize: 13 },
  delete: { color: '#c0392b', fontSize: 13 },
  editRow: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 },
  editInput: { flex: 1, borderWidth: 1, borderColor: '#007AFF', borderRadius: 6, padding: 6, fontSize: 14 },
  empty: { textAlign: 'center', color: '#999', marginTop: 40 },
});
