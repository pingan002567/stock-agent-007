import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  ImageBackground,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native';
import * as DocumentPicker from 'expo-document-picker';
import { useBottomTabBarHeight } from '@react-navigation/bottom-tabs';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useNetInfo } from '@react-native-community/netinfo';
import { deleteUpload, listUploads, uploadFiles } from '../api/client';
import { AssistantBubble } from '../components/AssistantBubble';
import { EmptyState, ErrorStrip } from '../components/ErrorState';
import { SessionDrawer } from '../components/SessionDrawer';
import { Sheet } from '../components/Sheet';
import { STARTER_PROMPTS } from '../lib/toolLabels';
import type { RootStackParamList } from '../navigation';
import { useThemedStyles, useTokens } from '../lib/tokens';
import { useAppearance } from '../store/appearance';
import { useChat } from '../store/chat';
import { useConnection } from '../store/connection';
import { usePrefill } from '../store/prefill';
import type { SessionUpload, Turn } from '../types';

const SESSION_REFRESH_MS = 30_000;

// 稳定引用：selector 里绝不能返回新建的 []，否则 useSyncExternalStore 会判定快照变化而无限重渲染
const EMPTY_TURNS: Turn[] = [];

export default function ChatScreen() {
  const styles = useThemedStyles(baseStyles);
  const insets = useSafeAreaInsets();
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const tabBarHeight = useBottomTabBarHeight();
  const t = useTokens();
  const { disconnect } = useConnection();
  const net = useNetInfo();
  const online = net.isConnected !== false;

  const currentSessionId = useChat((s) => s.currentSessionId);
  const sessions = useChat((s) => s.sessions);
  const activeStreams = useChat((s) => s.activeStreams);
  const loadingMore = useChat((s) => s.loadingMore);
  const loadingHistory = useChat((s) => s.loadingHistory);
  const chatError = useChat((s) => s.error);
  const notice = useChat((s) => s.notice);
  // selector 只返回已存在的数组或 undefined（两者引用都稳定），空值在外部兜底
  const turnsRaw = useChat((s) => (s.currentSessionId ? s.turnsBySession[s.currentSessionId] : undefined));
  const turns = turnsRaw ?? EMPTY_TURNS;
  const busy = useChat((s) => (s.currentSessionId ? !!s.activeStreams[s.currentSessionId] : false));
  const history = useChat((s) => (s.currentSessionId ? s.history[s.currentSessionId] : undefined));
  const draft = useChat((s) => (s.currentSessionId ? s.drafts[s.currentSessionId] ?? '' : ''));
  const dock = useChat((s) => (s.currentSessionId ? s.docks[s.currentSessionId] : undefined));
  const wallpaper = useAppearance((s) => s.backgroundUri);
  const dim = useAppearance((s) => s.dim);

  const [drawerVisible, setDrawerVisible] = useState(false);
  const [menuVisible, setMenuVisible] = useState(false);
  const [pendingUploads, setPendingUploads] = useState<SessionUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const listRef = useRef<FlatList<Turn>>(null);
  const askContextRef = useRef<{ page?: string; symbol?: string } | undefined>(undefined);

  // 初始加载：会话列表 + 草稿 + 断线遗留的流（前台恢复）
  useEffect(() => {
    void useChat.getState().loadSessions();
    void useChat.getState().hydrate();
    void useChat.getState().recoverOnForeground();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 30s 会话列表自动刷新
  useEffect(() => {
    const timer = setInterval(() => void useChat.getState().loadSessions(), SESSION_REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  // 「在对话中分析」等跨页预填（带 page/symbol 上下文）
  useEffect(() => {
    const pre = usePrefill.getState().take();
    if (pre.text) {
      askContextRef.current = pre.context ?? undefined;
      const sid = useChat.getState().currentSessionId;
      if (sid) useChat.getState().rememberDraft(sid, pre.text);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currentTitle = useMemo(
    () => sessions.find((s) => s.session_id === currentSessionId)?.title ?? '对话',
    [sessions, currentSessionId]
  );

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const distance = contentSize.height - layoutMeasurement.height - contentOffset.y;
    setAtBottom(distance < 60);
    // 接近顶部时自动预取更早的消息（对齐 iOS ChatHistoryPager 的自动预取）
    if (contentOffset.y < 80) {
      const st = useChat.getState();
      const sid = st.currentSessionId;
      if (sid && st.history[sid]?.nextBefore && !st.loadingMore) void st.loadEarlier();
    }
  };

  const jumpToLatest = useCallback(() => {
    listRef.current?.scrollToEnd({ animated: true });
    setAtBottom(true);
  }, []);

  const pickAndUpload = async () => {
    const res = await DocumentPicker.getDocumentAsync({ multiple: true, copyToCacheDirectory: true });
    if (res.canceled) return;
    const files = res.assets.map((a) => ({ uri: a.uri, name: a.name, mimeType: a.mimeType ?? 'application/octet-stream' }));
    setUploading(true);
    try {
      let sid = useChat.getState().currentSessionId;
      if (!sid) {
        await useChat.getState().newSession();
        sid = useChat.getState().currentSessionId;
      }
      if (!sid) return;
      const { baseURL, token } = useConnection.getState();
      await uploadFiles(baseURL, token, sid, files);
      const list = await listUploads(baseURL, token, sid);
      setPendingUploads(list.files ?? []);
    } catch {
      /* 附件失败不阻塞对话 */
    } finally {
      setUploading(false);
    }
  };

  /** 附件逐项删除：本地移除 + 通知服务端删除（对齐 iOS per-file delete） */
  const removeUpload = async (filename: string) => {
    setPendingUploads((prev) => prev.filter((x) => x.filename !== filename));
    const sid = useChat.getState().currentSessionId;
    if (!sid) return;
    try {
      const { baseURL, token } = useConnection.getState();
      await deleteUpload(baseURL, token, sid, filename);
    } catch {
      /* 本地已移除，服务端失败不阻塞 */
    }
  };

  const send = async (text?: string) => {
    const value = (text ?? draft).trim();
    const sid = useChat.getState().currentSessionId;
    if ((!value && pendingUploads.length === 0) || busy || !online) return;
    if (sid) useChat.getState().rememberDraft(sid, '');
    const uploads = pendingUploads;
    setPendingUploads([]);
    setAtBottom(true);
    const ctx = askContextRef.current;
    askContextRef.current = undefined;
    await useChat.getState().send(value, uploads, undefined, ctx);
  };

  const renderTurn = ({ item }: { item: Turn }) => (
    <View style={styles.turn}>
      <View style={styles.userRow}>
        <View style={styles.userBubble}>
          <Text style={styles.userText} selectable>
            {item.userText}
          </Text>
        </View>
      </View>
      {item.sendState === 'pending' ? <Text style={styles.sendStatus}>等待发送</Text> : null}
      {item.sendState === 'failed' ? (
        <Pressable onPress={() => void useChat.getState().retryTurn(item.id)}>
          <Text style={[styles.sendStatus, styles.sendStatusFailed]}>发送失败 · 点击重试</Text>
        </Pressable>
      ) : null}
      {item.assistant ? (
        <View style={styles.assistantRow}>
          <AssistantBubble
            assistant={item.assistant}
            turnId={item.id}
            userText={item.userText}
            onRetry={() => void useChat.getState().retryTurn(item.id)}
            onReplyClarification={(resp) => void useChat.getState().replyClarification(resp)}
            onOpenDetail={(tid, tab) => navigation.navigate('TurnDetail', { turnId: tid, initialTab: tab })}
          />
        </View>
      ) : null}
    </View>
  );

  const list = (
    <FlatList
      ref={listRef}
      data={turns}
      keyExtractor={(t) => t.id}
      renderItem={renderTurn}
      contentContainerStyle={styles.listContent}
      onScroll={onScroll}
      scrollEventThrottle={16}
      // 加载更早的消息时保持当前可见位置，避免被拽到底部
      maintainVisibleContentPosition={{ minIndexForVisible: 0, autoscrollToTopThreshold: 10 }}
      ListHeaderComponent={
        history?.hasMore ? (
          <Pressable style={styles.loadEarlier} onPress={() => void useChat.getState().loadEarlier()}>
            {loadingMore ? <ActivityIndicator size="small" /> : <Text style={styles.loadEarlierText}>上滑加载更早的消息</Text>}
          </Pressable>
        ) : turns.length > 0 ? (
          <Text style={styles.noMore}>没有更多了</Text>
        ) : null
      }
      ListEmptyComponent={
        loadingHistory ? (
          <ActivityIndicator style={{ marginTop: 40 }} />
        ) : (
          <View style={styles.starters}>
            <Text style={styles.startersTitle}>试试这些</Text>
            {STARTER_PROMPTS.map((s) => (
              <Pressable key={s.label} style={styles.starterBtn} onPress={() => void send(s.prompt)}>
                <Text style={styles.starterText}>{s.label}</Text>
              </Pressable>
            ))}
          </View>
        )
      }
    />
  );

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? tabBarHeight : 0}
    >
      {/* 浅灰岛头部：左 ☰ / 中标题 / 右 ✎新建 + ⋮更多 */}
      <View style={[styles.headerWrap, { paddingTop: insets.top + 8 }]}>
        <View style={styles.island}>
          <Pressable style={styles.circleBtn} onPress={() => setDrawerVisible(true)} hitSlop={4}>
            <Ionicons name="menu" size={20} color={t.text} />
          </Pressable>
          <Text style={styles.islandTitle} numberOfLines={1}>
            {currentTitle}
          </Text>
          <Pressable
            style={styles.circleBtn}
            onPress={() => void useChat.getState().newSession()}
            hitSlop={4}
          >
            <Ionicons name="create-outline" size={19} color={t.text} />
          </Pressable>
          <Pressable style={styles.circleBtn} onPress={() => setMenuVisible(true)} hitSlop={4}>
            <Ionicons name="ellipsis-vertical" size={19} color={t.text} />
          </Pressable>
        </View>
      </View>

      {!online ? (
        <ErrorStrip
          message="你似乎已离线。请重新连接以发送消息。"
          onRetry={() => {
            void useConnection.getState().reprobeHealth();
            void useChat.getState().recoverOnForeground();
          }}
        />
      ) : null}
      <ErrorStrip
        message={chatError ?? ''}
        onRetry={() => void useChat.getState().recoverOnForeground()}
        onDismiss={() => useChat.getState().setError(null)}
      />
      {notice ? (
        <Pressable onPress={() => useChat.getState().clearNotice()}>
          <Text style={styles.notice}>{notice}</Text>
        </Pressable>
      ) : null}

      {wallpaper ? (
        <ImageBackground source={{ uri: wallpaper }} style={styles.bg} imageStyle={{ opacity: 1 - dim }}>
          {list}
        </ImageBackground>
      ) : (
        <View style={styles.bg}>{list}</View>
      )}

      {!atBottom && turns.length > 0 ? (
        <Pressable style={styles.jumpBtn} onPress={jumpToLatest}>
          <Text style={styles.jumpText}>↓ 最新</Text>
        </Pressable>
      ) : null}

      {pendingUploads.length > 0 ? (        <View style={styles.uploadStrip}>
          {pendingUploads.map((u) => (
            <Pressable key={u.filename} style={styles.uploadChip} onPress={() => void removeUpload(u.filename)}>
              <Text style={styles.uploadChipText}>{u.filename} ✕</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {dock ? (
        <View style={[styles.dock, dock === 'stuck' && styles.dockStuck]}>
          <Text style={styles.dockTitle}>{dock === 'stuck' ? '长时间没有新进展' : '正在处理…'}</Text>
          <Text style={styles.dockDetail}>
            {dock === 'stuck' ? '已超过 90 秒未收到进展，可继续等待或点停止重试' : '已连上，等待模型输出'}
          </Text>
        </View>
      ) : null}

      <View style={styles.composerWrap}>
        <View style={styles.composerPill}>
          <Pressable
            style={styles.pillIcon}
            onPress={() => void pickAndUpload()}
            disabled={uploading || !online}
            hitSlop={4}
          >
            {uploading ? (
              <ActivityIndicator size="small" />
            ) : (
              <Ionicons name="add" size={24} color={online ? t.sub : t.border} />
            )}
          </Pressable>

          <TextInput
            style={styles.pillInput}
            value={draft}
            onChangeText={(v) => currentSessionId && useChat.getState().rememberDraft(currentSessionId, v)}
            placeholder={online ? '问 Stock Agent…' : '网络不可用，暂不可发送'}
            placeholderTextColor={t.sub}
            multiline
            editable={online}
          />

          {busy ? (
            <Pressable style={styles.sendCircle} onPress={() => useChat.getState().stop()} hitSlop={4}>
              <Ionicons name="stop" size={18} color="#fff" />
            </Pressable>
          ) : (
            <Pressable
              style={[styles.sendCircle, (!draft.trim() || !online) && styles.sendCircleDisabled]}
              onPress={() => void send()}
              disabled={!draft.trim() || !online}
              hitSlop={4}
            >
              <Ionicons name="arrow-up" size={20} color={!draft.trim() || !online ? t.sub : '#fff'} />
            </Pressable>
          )}
        </View>
      </View>

      {/* ⋮ 更多 */}
      <Sheet visible={menuVisible} onClose={() => setMenuVisible(false)}>
        <Text style={styles.sheetTitle} numberOfLines={1}>
          {currentTitle}
        </Text>
        <MenuItem
          icon="add-circle-outline"
          label="新建对话"
          onPress={() => {
            setMenuVisible(false);
            void useChat.getState().newSession();
          }}
        />
        <MenuItem
          icon="albums-outline"
          label="管理对话（重命名 / 删除）"
          onPress={() => {
            setMenuVisible(false);
            setDrawerVisible(true);
          }}
        />
        <MenuItem
          icon="refresh-outline"
          label="重新探测连接"
          onPress={() => {
            setMenuVisible(false);
            void useConnection.getState().reprobeHealth();
          }}
        />
        <MenuItem
          icon="log-out-outline"
          label="断开连接"
          danger
          onPress={() => {
            setMenuVisible(false);
            disconnect();
          }}
        />
      </Sheet>

      <SessionDrawer
        visible={drawerVisible}
        onClose={() => setDrawerVisible(false)}
        sessions={sessions}
        currentSessionId={currentSessionId}
        activeStreams={activeStreams}
        onNew={() => {
          void useChat.getState().newSession();
          setDrawerVisible(false);
        }}
        onOpen={(id) => {
          void useChat.getState().openSession(id);
          setDrawerVisible(false);
        }}
        onRename={(id, title) => void useChat.getState().renameSession(id, title)}
        onDelete={(id) => void useChat.getState().removeSession(id)}
      />
    </KeyboardAvoidingView>
  );
}

function MenuItem({
  icon,
  label,
  onPress,
  danger,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  onPress: () => void;
  danger?: boolean;
}) {
  const styles = useThemedStyles(baseStyles);
  return (
    <Pressable style={styles.menuItem} onPress={onPress}>
      <Ionicons name={icon} size={20} color={danger ? '#FF3B30' : '#333'} />
      <Text style={[styles.menuLabel, danger && styles.menuLabelDanger]}>{label}</Text>
    </Pressable>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  bg: { flex: 1 },
  headerWrap: { paddingHorizontal: 10, paddingBottom: 6 },
  island: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#f2f2f7',
    borderRadius: 26,
    paddingHorizontal: 6,
    paddingVertical: 6,
    gap: 4,
  },
  circleBtn: {
    width: 38,
    height: 38,
    borderRadius: 19,
    backgroundColor: '#fff',
    alignItems: 'center',
    justifyContent: 'center',
  },
  islandTitle: { flex: 1, fontSize: 14, fontWeight: '600', textAlign: 'center', color: '#111' },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 22,
    paddingVertical: 14,
  },
  menuLabel: { fontSize: 15, color: '#111' },
  menuLabelDanger: { color: '#FF3B30' },
  sheetTitle: {
    fontSize: 13,
    color: '#8E8E93',
    textAlign: 'center',
    paddingHorizontal: 20,
    paddingTop: 8,
    paddingBottom: 12,
  },
  headerTitle: { flex: 1, fontSize: 16, fontWeight: '600', textAlign: 'center' },
  disconnect: { color: '#007AFF', fontSize: 14 },
  notice: { backgroundColor: '#007AFF15', color: '#007AFF', fontSize: 12, paddingHorizontal: 14, paddingVertical: 6 },
  listContent: { padding: 16, flexGrow: 1 },
  turn: { marginBottom: 16 },
  userRow: { alignItems: 'flex-end', marginBottom: 6 },
  userBubble: { backgroundColor: '#007AFF', borderRadius: 18, paddingHorizontal: 14, paddingVertical: 10, maxWidth: '85%' },
  userText: { color: '#fff', fontSize: 15, lineHeight: 21 },
  sendStatus: { textAlign: 'right', fontSize: 11, color: '#8E8E93', marginTop: 4 },
  sendStatusFailed: { color: '#FF3B30' },
  assistantRow: { alignItems: 'flex-start' },
  loadEarlier: { alignSelf: 'center', paddingVertical: 10 },
  loadEarlierText: { color: '#007AFF', fontSize: 13 },
  noMore: { textAlign: 'center', color: '#C7C7CC', fontSize: 12, paddingVertical: 10 },
  starters: { paddingTop: 24 },
  startersTitle: { textAlign: 'center', color: '#8E8E93', fontSize: 13, marginBottom: 12 },
  starterBtn: {
    borderWidth: 1,
    borderColor: '#007AFF40',
    backgroundColor: '#007AFF0D',
    borderRadius: 10,
    padding: 14,
    marginBottom: 10,
  },
  starterText: { color: '#007AFF', fontSize: 14 },
  jumpBtn: {
    position: 'absolute',
    right: 16,
    bottom: 96,
    backgroundColor: '#007AFF',
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  jumpText: { color: '#fff', fontSize: 13, fontWeight: '600' },
  uploadStrip: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, paddingHorizontal: 16, paddingBottom: 4 },  uploadChip: { backgroundColor: '#eef3f8', borderRadius: 12, paddingHorizontal: 10, paddingVertical: 4 },
  uploadChipText: { fontSize: 12, color: '#334' },
  dock: { paddingHorizontal: 14, paddingVertical: 6, backgroundColor: '#007AFF1A' },
  dockStuck: { backgroundColor: '#FF950022' },
  dockTitle: { fontSize: 12, fontWeight: '600', color: '#333' },
  dockDetail: { fontSize: 11, color: '#666' },
  composerWrap: { paddingHorizontal: 12, paddingTop: 6, paddingBottom: 8 },
  composerPill: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: '#f7f7f9',
    borderRadius: 26,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#e5e5ea',
    paddingHorizontal: 4,
    paddingVertical: 4,
    minHeight: 50,
  },
  pillIcon: { width: 38, height: 38, alignItems: 'center', justifyContent: 'center' },
  pillInput: { flex: 1, fontSize: 15, maxHeight: 120, paddingVertical: 10, paddingHorizontal: 2 },
  sendCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#007AFF',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 2,
  },
  sendCircleDisabled: { backgroundColor: '#e5e5ea' },
  composer: { flexDirection: 'row', alignItems: 'flex-end', padding: 8 },
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
  input: { flex: 1, borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 10, fontSize: 15, maxHeight: 120 },
  sendBtn: { backgroundColor: '#007AFF', borderRadius: 8, paddingHorizontal: 18, paddingVertical: 12, marginLeft: 8 },
  sendDisabled: { opacity: 0.4 },
  sendText: { color: '#fff', fontWeight: '600' },
});
