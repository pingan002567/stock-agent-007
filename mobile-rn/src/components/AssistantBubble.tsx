import { useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import type { AssistantState, Clarification } from '../types';
import { Markdown, StreamMarkdown } from './Markdown';

interface Props {
  assistant: AssistantState;
  onReplyClarification?: (response: Record<string, unknown>) => void;
  onRetry?: () => void;
}

const PHASE_LABEL: Record<AssistantState['phase'], string> = {
  reasoning: '思考中…',
  tools: '调用工具…',
  answering: '生成中…',
  final: '',
  clarification: '',
  error: '',
};

export function AssistantBubble({ assistant, onReplyClarification, onRetry }: Props) {
  const [showReasoning, setShowReasoning] = useState(false);
  const [showTool, setShowTool] = useState<string | null>(null);

  const streaming = assistant.streaming;
  const phaseLabel = streaming ? PHASE_LABEL[assistant.phase] : '';

  return (
    <View style={styles.container}>
      {phaseLabel ? <Text style={styles.phase}>{phaseLabel}</Text> : null}

      {assistant.reasoningText ? (
        <Pressable style={styles.collapse} onPress={() => setShowReasoning((v) => !v)}>
          <Text style={styles.collapseText}>
            {showReasoning ? '▾ 思考过程' : '▸ 思考过程'}
          </Text>
          {showReasoning ? <Text style={styles.reasoning}>{assistant.reasoningText}</Text> : null}
        </Pressable>
      ) : null}

      {assistant.tools.length > 0 ? (
        <View style={styles.tools}>
          {assistant.tools.map((t) => (
            <Pressable key={t.id} style={styles.toolChip} onPress={() => setShowTool((cur) => (cur === t.id ? null : t.id))}>
              <Text style={styles.toolName}>
                {t.status === 'running' ? '⏳' : '✓'} {t.name}
              </Text>
              {showTool === t.id && t.resultPreview ? (
                <Text style={styles.toolPreview}>{t.resultPreview}</Text>
              ) : null}
            </Pressable>
          ))}
        </View>
      ) : null}

      {assistant.answerText ? (
        streaming ? (
          <StreamMarkdown text={assistant.answerText} streaming />
        ) : (
          <Markdown text={assistant.answerText} />
        )
      ) : streaming ? null : null}

      {assistant.clarification ? (
        <ClarificationCard clarification={assistant.clarification} onReply={onReplyClarification} />
      ) : null}

      {assistant.failed ? (
        <View style={styles.failedBox}>
          <Text style={styles.failedText}>{assistant.answerText || '生成失败'}</Text>
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
  const [free, setFree] = useState('');
  const submitText = (value: string) => {
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

  return (
    <View style={styles.clarify}>
      <Text style={styles.clarifyQ}>{clarification.question}</Text>
      {clarification.options.map((o) => (
        <Pressable key={o.id} style={styles.clarifyOpt} onPress={() => submitOption(o.id, o.value)}>
          <Text style={styles.clarifyOptText}>{o.label}</Text>
        </Pressable>
      ))}
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
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: 12, backgroundColor: '#f4f6f8', borderRadius: 12, maxWidth: '92%' },
  phase: { fontSize: 12, color: '#888', marginBottom: 6 },
  collapse: { marginBottom: 6 },
  collapseText: { fontSize: 13, color: '#007AFF' },
  reasoning: { fontSize: 13, color: '#666', lineHeight: 19, marginTop: 4 },
  tools: { marginBottom: 6 },
  toolChip: { backgroundColor: '#e8eef4', borderRadius: 6, padding: 6, marginBottom: 4 },
  toolName: { fontSize: 12, color: '#334' },
  toolPreview: { fontSize: 11, color: '#667', marginTop: 4 },
  failedBox: { marginTop: 4 },
  failedText: { color: '#c0392b', fontSize: 14 },
  retryBtn: { marginTop: 8, backgroundColor: '#007AFF', borderRadius: 6, padding: 8, alignSelf: 'flex-start' },
  retryText: { color: '#fff', fontSize: 13 },
  clarify: { marginTop: 8 },
  clarifyQ: { fontSize: 14, fontWeight: '600', marginBottom: 6 },
  clarifyOpt: { backgroundColor: '#fff', borderWidth: 1, borderColor: '#007AFF', borderRadius: 6, padding: 8, marginBottom: 6 },
  clarifyOptText: { color: '#007AFF', fontSize: 14 },
  clarifyRow: { flexDirection: 'row', marginTop: 4 },
  clarifyInput: { flex: 1, borderWidth: 1, borderColor: '#ccc', borderRadius: 6, padding: 8, fontSize: 14 },
  clarifySend: { marginLeft: 8, backgroundColor: '#007AFF', borderRadius: 6, paddingHorizontal: 14, justifyContent: 'center' },
  clarifySendText: { color: '#fff' },
});
