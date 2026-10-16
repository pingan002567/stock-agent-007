import { useState } from 'react';
import { Pressable, Share, StyleSheet, Text, TextInput, View } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import { toolLabel } from '../lib/toolLabels';
import type { AssistantState, Clarification } from '../types';
import { Markdown, StreamMarkdown } from './Markdown';
import { useThemedStyles } from '../lib/tokens';

interface Props {
  assistant: AssistantState;
  turnId: string;
  userText: string;
  onRetry?: () => void;
  onReplyClarification?: (response: Record<string, unknown>) => void;
  onOpenDetail?: (turnId: string) => void;
}

const PHASE_LABEL: Record<AssistantState['phase'], string> = {
  reasoning: '思考中…',
  tools: '调用工具…',
  answering: '生成中…',
  final: '',
  clarification: '',
  error: '',
};

const COLLAPSE_CHARS = 280;
const COLLAPSE_LINES = 5;

export function AssistantBubble({ assistant, turnId, userText, onRetry, onReplyClarification, onOpenDetail }: Props) {
  const styles = useThemedStyles(baseStyles);
  const [showReasoning, setShowReasoning] = useState(false);
  const [showSkill, setShowSkill] = useState(false);
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const streaming = assistant.streaming;
  const answer = assistant.answerText;
  const lineCount = answer.split('\n').length;
  const isLong = answer.length > COLLAPSE_CHARS || lineCount > COLLAPSE_LINES;
  const runningTools = assistant.tools.filter((t) => t.status === 'running').length;
  const phaseLabel = streaming
    ? assistant.phase === 'tools' && runningTools > 0
      ? `调用工具…（${runningTools} 个运行中）`
      : PHASE_LABEL[assistant.phase]
    : '';

  const copy = async (text: string) => {
    await Clipboard.setStringAsync(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const share = async (text: string) => {
    try {
      await Share.share({ message: text });
    } catch {
      /* ignore */
    }
  };

  return (
    <View style={styles.container}>
      {phaseLabel ? <Text style={styles.phase}>{phaseLabel}</Text> : null}

      {assistant.reasoningText ? (
        <Pressable style={styles.collapse} onPress={() => setShowReasoning((v) => !v)}>
          <Text style={styles.collapseText}>
            {showReasoning ? '▾ 思考过程' : `▸ 思考过程 · ${assistant.reasoningText.slice(0, 40)}…`}
          </Text>
          {showReasoning ? (
            <Text style={styles.reasoning} selectable>
              {assistant.reasoningText}
            </Text>
          ) : null}
        </Pressable>
      ) : null}

      {assistant.skillTrace.length > 0 ? (
        <Pressable style={styles.collapse} onPress={() => setShowSkill((v) => !v)}>
          <Text style={styles.collapseText}>{showSkill ? '▾ 技能执行' : `▸ 技能执行 · ${assistant.skillTrace.length} 步`}</Text>
          {showSkill
            ? assistant.skillTrace.map((s, i) => (
                <Text key={i} style={styles.skillLine}>
                  {s.step != null ? `${s.step}. ` : ''}
                  {s.label ?? s.skill}
                  {s.status ? ` · ${s.status}` : ''}
                </Text>
              ))
            : null}
        </Pressable>
      ) : null}

      {assistant.tools.length > 0 ? (
        <View style={styles.tools}>
          <Text style={styles.toolCount}>
            工具 {assistant.tools.filter((t) => t.status === 'done').length}/{assistant.tools.length}
          </Text>
          {assistant.tools.map((t) => (
            <Pressable
              key={t.id}
              style={styles.toolChip}
              onPress={() => setExpandedTool((cur) => (cur === t.id ? null : t.id))}
            >
              <Text style={styles.toolName}>
                {t.status === 'running' ? '⏳' : '✓'} {toolLabel(t.name)}
              </Text>
              {expandedTool === t.id ? (
                <Text style={styles.toolPreview} selectable>
                  {t.resultPreview || '暂无结果预览'}
                </Text>
              ) : null}
            </Pressable>
          ))}
        </View>
      ) : null}

      {answer ? (
        <View>
          {streaming ? (
            <StreamMarkdown text={answer} streaming />
          ) : isLong ? (
            <Text style={styles.collapsedAnswer} numberOfLines={COLLAPSE_LINES}>
              {answer}
            </Text>
          ) : (
            <Markdown text={answer} />
          )}
          {streaming && assistant.phase === 'answering' ? <Text style={styles.cursor}>▍</Text> : null}
        </View>
      ) : null}

      {!streaming && answer ? (
        <View style={styles.actions}>
          <Pressable onPress={() => void copy(answer)} hitSlop={6}>
            <Text style={styles.actionText}>{copied ? '已复制' : '复制'}</Text>
          </Pressable>
          <Pressable onPress={() => void share(answer)} hitSlop={6}>
            <Text style={styles.actionText}>分享</Text>
          </Pressable>
          {isLong && onOpenDetail ? (
            <Pressable onPress={() => onOpenDetail(turnId)} hitSlop={6}>
              <Text style={styles.actionText}>查看完整回答</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {assistant.clarification ? (
        <ClarificationCard clarification={assistant.clarification} onReply={onReplyClarification} />
      ) : null}

      {assistant.failed ? (
        <View style={styles.failedBox}>
          <Text style={styles.failedText}>{answer || '生成失败'}</Text>
          {onRetry ? (
            <Pressable style={styles.retryBtn} onPress={onRetry}>
              <Text style={styles.retryText}>重试</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function ClarificationCard({
  clarification,
  onReply,
}: {
  clarification: Clarification;
  onReply?: (response: Record<string, unknown>) => void;
}) {
  const styles = useThemedStyles(baseStyles);
  const [free, setFree] = useState('');
  const [answered, setAnswered] = useState(false);

  const submitText = (value: string) => {
    setAnswered(true);
    onReply?.({
      version: 1,
      kind: 'human_input_response',
      source: 'ask_clarification',
      request_id: clarification.requestId,
      response_kind: 'text',
      value,
    });
  };
  const submitOption = (optionId: string, value: string) => {
    setAnswered(true);
    onReply?.({
      version: 1,
      kind: 'human_input_response',
      source: 'ask_clarification',
      request_id: clarification.requestId,
      response_kind: 'option',
      option_id: optionId,
      value,
    });
  };

  const choiceMode = clarification.inputMode !== 'free_text';

  return (
    <View style={styles.clarify}>
      <Text style={styles.clarifyQ}>{clarification.question}</Text>
      {answered ? (
        <Text style={styles.answered}>已回答</Text>
      ) : (
        <>
          {choiceMode
            ? clarification.options.map((o) => (
                <Pressable key={o.id} style={styles.clarifyOpt} onPress={() => submitOption(o.id, o.value)}>
                  <Text style={styles.clarifyOptText}>{o.label}</Text>
                </Pressable>
              ))
            : null}
          <View style={styles.clarifyRow}>
            <TextInput
              style={styles.clarifyInput}
              placeholder="输入你的回答"
              value={free}
              onChangeText={setFree}
              onSubmitEditing={() => free.trim() && submitText(free.trim())}
            />
            <Pressable style={styles.clarifySend} onPress={() => free.trim() && submitText(free.trim())}>
              <Text style={styles.clarifySendText}>提交</Text>
            </Pressable>
          </View>
        </>
      )}
    </View>
  );
}

const baseStyles = StyleSheet.create({
  container: { padding: 12, backgroundColor: '#f4f6f8', borderRadius: 12, maxWidth: '92%' },
  phase: { fontSize: 12, color: '#8E8E93', marginBottom: 6 },
  collapse: { marginBottom: 6 },
  collapseText: { fontSize: 13, color: '#007AFF' },
  reasoning: { fontSize: 13, color: '#666', lineHeight: 19, marginTop: 4 },
  skillLine: { fontSize: 12, color: '#555', marginTop: 3 },
  tools: { marginBottom: 6 },
  toolCount: { fontSize: 11, color: '#8E8E93', marginBottom: 4 },
  toolChip: { backgroundColor: '#e8eef4', borderRadius: 6, padding: 6, marginBottom: 4 },
  toolName: { fontSize: 12, color: '#334' },
  toolPreview: { fontSize: 11, color: '#667', marginTop: 4 },
  collapsedAnswer: { fontSize: 15, lineHeight: 22 },
  cursor: { color: '#007AFF', fontSize: 15 },
  actions: { flexDirection: 'row', gap: 18, marginTop: 10 },
  actionText: { color: '#007AFF', fontSize: 13 },
  failedBox: { marginTop: 4 },
  failedText: { color: '#FF3B30', fontSize: 14 },
  retryBtn: { marginTop: 8, backgroundColor: '#007AFF', borderRadius: 6, padding: 8, alignSelf: 'flex-start' },
  retryText: { color: '#fff', fontSize: 13 },
  clarify: { marginTop: 8 },
  clarifyQ: { fontSize: 14, fontWeight: '600', marginBottom: 6 },
  answered: { fontSize: 13, color: '#34C759' },
  clarifyOpt: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#007AFF',
    borderRadius: 6,
    padding: 8,
    marginBottom: 6,
  },
  clarifyOptText: { color: '#007AFF', fontSize: 14 },
  clarifyRow: { flexDirection: 'row', marginTop: 4 },
  clarifyInput: { flex: 1, borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, fontSize: 14 },
  clarifySend: {
    marginLeft: 8,
    backgroundColor: '#007AFF',
    borderRadius: 6,
    paddingHorizontal: 14,
    justifyContent: 'center',
  },
  clarifySendText: { color: '#fff' },
});
