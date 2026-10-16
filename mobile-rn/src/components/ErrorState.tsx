import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useThemedStyles } from '../lib/tokens';

/** 失败态（对齐 iOS ContentUnavailableView("加载失败")）——必须与「空」区分开。 */
export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const styles = useThemedStyles(baseStyles);
  return (
    <View style={styles.wrap}>
      <Text style={styles.icon}>⚠️</Text>
      <Text style={styles.title}>加载失败</Text>
      {message ? <Text style={styles.detail} numberOfLines={4}>{message}</Text> : null}
      {onRetry ? (
        <Pressable style={styles.retry} onPress={onRetry}>
          <Text style={styles.retryText}>重试</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/** 空态 */
export function EmptyState({ text, hint }: { text: string; hint?: string }) {
  const styles = useThemedStyles(baseStyles);
  return (
    <View style={styles.wrap}>
      <Text style={styles.emptyText}>{text}</Text>
      {hint ? <Text style={styles.detail}>{hint}</Text> : null}
    </View>
  );
}

export function LoadingState() {
  return <ActivityIndicator style={{ marginTop: 40 }} />;
}

/** 列表区统一渲染：错误 > 加载 > 空 */
export function listState(opts: { loading: boolean; error?: string | null; empty: boolean; emptyText: string; onRetry?: () => void }) {
  if (opts.error) return <ErrorState message={opts.error} onRetry={opts.onRetry} />;
  if (opts.loading) return <LoadingState />;
  if (opts.empty) return <EmptyState text={opts.emptyText} />;
  return null;
}

/** 顶部内联错误条（对话页等） */
export function ErrorStrip({
  message,
  onDismiss,
  onRetry,
}: {
  message: string;
  onDismiss?: () => void;
  onRetry?: () => void;
}) {
  const styles = useThemedStyles(baseStyles);
  if (!message) return null;
  return (
    <View style={styles.card}>
      <Ionicons name="cloud-offline-outline" size={20} color="#8E8E93" />
      <Text style={styles.cardText}>{message}</Text>
      {onRetry ? (
        <Pressable onPress={onRetry} hitSlop={8}>
          <Ionicons name="refresh" size={20} color="#8E8E93" />
        </Pressable>
      ) : null}
      {onDismiss ? (
        <Pressable onPress={onDismiss} hitSlop={8}>
          <Ionicons name="close" size={18} color="#8E8E93" />
        </Pressable>
      ) : null}
    </View>
  );
}

const baseStyles = StyleSheet.create({
  wrap: { alignItems: 'center', paddingHorizontal: 32, paddingVertical: 40 },
  icon: { fontSize: 28, marginBottom: 8 },
  title: { fontSize: 15, fontWeight: '600', color: '#333' },
  emptyText: { fontSize: 14, color: '#8E8E93' },
  detail: { fontSize: 12, color: '#8E8E93', marginTop: 6, textAlign: 'center' },
  retry: { marginTop: 14, borderWidth: 1, borderColor: '#007AFF', borderRadius: 8, paddingHorizontal: 18, paddingVertical: 8 },
  retryText: { color: '#007AFF', fontSize: 14, fontWeight: '600' },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    marginHorizontal: 12,
    marginVertical: 6,
    padding: 12,
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: '#e5e5ea',
    backgroundColor: '#f7f7f9',
  },
  cardText: { flex: 1, color: '#333', fontSize: 13, lineHeight: 19 },
  strip: { flexDirection: 'row', alignItems: 'center', backgroundColor: '#FF3B3015', paddingHorizontal: 14, paddingVertical: 8 },
  stripText: { flex: 1, color: '#FF3B30', fontSize: 12 },
  stripClose: { color: '#FF3B30', fontSize: 13, marginLeft: 10 },
});
