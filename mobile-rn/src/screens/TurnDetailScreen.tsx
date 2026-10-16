import { useState } from 'react';
import { Pressable, ScrollView, Share, StyleSheet, Text, View } from 'react-native';
import { useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import * as Clipboard from 'expo-clipboard';
import { EmptyState, ErrorState } from '../components/ErrorState';
import { Markdown, StreamMarkdown } from '../components/Markdown';
import { toolLabel } from '../lib/toolLabels';
import type { RootStackParamList } from '../navigation';
import { useChat } from '../store/chat';
import { useThemedStyles } from '../lib/tokens';

type Route = RouteProp<RootStackParamList, 'TurnDetail'>;
type Tab = 'answer' | 'tools' | 'reasoning';

export default function TurnDetailScreen() {
  const styles = useThemedStyles(baseStyles);
  const route = useRoute<Route>();
  const { turnId } = route.params;
  const turn = useChat((s) => {
    if (!s.currentSessionId) return undefined;
    return (s.turnsBySession[s.currentSessionId] ?? []).find((t) => t.id === turnId);
  });
  const [tab, setTab] = useState<Tab>('answer');
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  if (!turn?.assistant) return <ErrorState message="未找到该轮回答" />;
  const a = turn.assistant;

  const tabs: { id: Tab; label: string }[] = [{ id: 'answer', label: '回答' }];
  if (a.tools.length > 0) tabs.push({ id: 'tools', label: '工具' });
  if (a.reasoningText.trim()) tabs.push({ id: 'reasoning', label: '思考' });

  const payload = tab === 'answer' ? a.answerText : tab === 'reasoning' ? a.reasoningText : '';

  const copy = (t: string) => void Clipboard.setStringAsync(t);
  const share = async (t: string) => {
    try {
      await Share.share({ message: t });
    } catch {
      /* ignore */
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.tabs}>
        {tabs.map((t) => (
          <Pressable key={t.id} style={[styles.tab, tab === t.id && styles.tabActive]} onPress={() => setTab(t.id)}>
            <Text style={[styles.tabText, tab === t.id && styles.tabTextActive]}>{t.label}</Text>
          </Pressable>
        ))}
      </View>

      {payload ? (
        <View style={styles.actions}>
          <Pressable onPress={() => copy(payload)} hitSlop={6}>
            <Text style={styles.actionText}>复制</Text>
          </Pressable>
          <Pressable onPress={() => void share(payload)} hitSlop={6}>
            <Text style={styles.actionText}>分享</Text>
          </Pressable>
        </View>
      ) : null}

      <ScrollView contentContainerStyle={styles.body}>
        {tab === 'answer' ? (
          a.answerText ? (
            a.streaming ? (
              <StreamMarkdown text={a.answerText} streaming />
            ) : (
              <Markdown text={a.answerText} />
            )
          ) : (
            <EmptyState text={a.streaming ? '正在生成' : '暂无正文'} />
          )
        ) : null}

        {tab === 'tools' ? (
          a.tools.length === 0 ? (
            <EmptyState text="本轮没有工具调用" />
          ) : (
            a.tools.map((t) => (
              <Pressable
                key={t.id}
                style={styles.toolCard}
                onPress={() => setExpandedTool((cur) => (cur === t.id ? null : t.id))}
              >
                <View style={styles.toolHead}>
                  <Text style={styles.toolStatus}>{t.status === 'running' ? '⏳' : '✓'}</Text>
                  <Text style={styles.toolName}>{toolLabel(t.name)}</Text>
                </View>
                {expandedTool === t.id ? (
                  <Text style={styles.toolResult} selectable>
                    {t.resultPreview || '暂无结果预览'}
                  </Text>
                ) : null}
              </Pressable>
            ))
          )
        ) : null}

        {tab === 'reasoning' ? (
          a.reasoningText.trim() ? (
            <Text style={styles.reasoning} selectable>
              {a.reasoningText}
            </Text>
          ) : (
            <EmptyState text="本轮没有思考内容" />
          )
        ) : null}

        <View style={styles.footer}>
          <Text style={styles.footerText}>字数 · {a.answerText.length} · 工具 · {a.tools.length}</Text>
        </View>
      </ScrollView>
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  tabs: { flexDirection: 'row', paddingHorizontal: 16, paddingVertical: 10, gap: 8 },
  tab: { flex: 1, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: '#ddd', alignItems: 'center' },
  tabActive: { borderColor: '#007AFF', backgroundColor: '#eef4ff' },
  tabText: { fontSize: 13, color: '#666' },
  tabTextActive: { color: '#007AFF', fontWeight: '600' },
  actions: { flexDirection: 'row', gap: 18, paddingHorizontal: 16, paddingBottom: 6 },
  actionText: { color: '#007AFF', fontSize: 13 },
  body: { padding: 16 },
  toolCard: { backgroundColor: '#f6f8fa', borderRadius: 10, padding: 12, marginBottom: 10 },
  toolHead: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  toolStatus: { fontSize: 13 },
  toolName: { fontSize: 14, fontWeight: '600' },
  toolResult: { fontSize: 12, color: '#555', marginTop: 8, fontFamily: 'Menlo' },
  reasoning: { fontSize: 14, color: '#555', lineHeight: 21 },
  footer: { marginTop: 24, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#eee', paddingTop: 8 },
  footerText: { fontSize: 11, color: '#C7C7CC' },
});
