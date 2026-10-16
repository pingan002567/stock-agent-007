import { memo, useMemo } from 'react';
import { Linking, ScrollView, StyleSheet, Text, View } from 'react-native';
import {
  parseInline,
  parseMarkdownBlocks,
  splitStableBlocks,
  STREAM_TAIL_PLAIN_TEXT_THRESHOLD,
  type InlineSegment,
  type MdBlock,
} from '../lib/markdown';
import { useThemedStyles } from '../lib/tokens';

const mono = { fontFamily: 'Menlo', fontSize: 13, color: '#c0392b' } as const;

function Inline({ segments }: { segments: InlineSegment[] }) {
  const styles = useThemedStyles(baseStyles);
  const nodes = segments.map((s, i) => {
    if (s.kind === 'bold') return <Text key={i} style={styles.bold}>{s.text}</Text>;
    if (s.kind === 'code') return <Text key={i} style={mono}>{s.text}</Text>;
    if (s.kind === 'link') {
      return (
        <Text key={i} style={styles.link} onPress={() => Linking.openURL(s.url).catch(() => {})}>
          {s.text}
        </Text>
      );
    }
    return <Text key={i}>{s.text}</Text>;
  });
  return <Text>{nodes}</Text>;
}

function Block({ block }: { block: MdBlock }) {
  const styles = useThemedStyles(baseStyles);
  switch (block.type) {
    case 'heading':
      return (
        <Text selectable style={[styles.heading, block.level >= 2 && styles.subHeading]}>
          <Inline segments={parseInline(block.text)} />
        </Text>
      );
    case 'hr':
      return <View style={styles.hr} />;
    case 'code':
      return (
        <View style={styles.codeBox}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <Text selectable style={mono}>
              {block.code}
            </Text>
          </ScrollView>
        </View>
      );
    case 'table':
      return (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tableWrap}>
          <View style={styles.table}>
            {block.headers.length > 0 && (
              <View style={styles.tableRow}>
                {block.headers.map((h, i) => (
                  <Text key={i} selectable style={[styles.cell, styles.th]}>
                    <Inline segments={parseInline(h)} />
                  </Text>
                ))}
              </View>
            )}
            {block.rows.map((row, ri) => (
              <View key={ri} style={[styles.tableRow, ri % 2 === 1 && styles.tableRowAlt]}>
                {row.map((cell, ci) => (
                  <Text key={ci} selectable style={styles.cell}>
                    <Inline segments={parseInline(cell)} />
                  </Text>
                ))}
              </View>
            ))}
          </View>
        </ScrollView>
      );
    case 'ol':
      return (
        <View style={styles.list}>
          {block.items.map((item, i) => (
            <Text key={i} selectable style={styles.listItem}>
              <Text style={styles.listMarker}>{i + 1}. </Text>
              <Inline segments={parseInline(item)} />
            </Text>
          ))}
        </View>
      );
    case 'ul':
      return (
        <View style={styles.list}>
          {block.items.map((item, i) => (
            <Text key={i} selectable style={styles.listItem}>
              <Text style={styles.listMarker}>• </Text>
              <Inline segments={parseInline(item)} />
            </Text>
          ))}
        </View>
      );
    case 'p':
      return (
        <Text selectable style={styles.p}>
          <Inline segments={parseInline(block.text)} />
        </Text>
      );
    default:
      return null;
  }
}

function MarkdownInner({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(text), [text]);
  return (
    <View>
      {blocks.map((b, i) => (
        <Block key={i} block={b} />
      ))}
    </View>
  );
}

export const Markdown = memo(MarkdownInner);

/** 流式友好：闭合块 memo，只重渲生长尾；尾段过长退化为纯文本。 */
export function StreamMarkdown({ text, streaming = true }: { text: string; streaming?: boolean }) {
  const styles = useThemedStyles(baseStyles);
  const { stable, tail } = useMemo(() => splitStableBlocks(text), [text]);

  if (!streaming) return <Markdown text={text} />;

  const usePlainTail = tail.length > STREAM_TAIL_PLAIN_TEXT_THRESHOLD;

  return (
    <View>
      {stable.map((block, i) => (
        <Markdown key={i} text={block} />
      ))}
      {tail ? (
        usePlainTail ? (
          <Text style={styles.p}>{tail}</Text>
        ) : (
          <Markdown text={tail} />
        )
      ) : null}
    </View>
  );
}

const baseStyles = StyleSheet.create({
  p: { fontSize: 15, lineHeight: 22, marginBottom: 8 },
  bold: { fontWeight: '700' },
  link: { color: '#007AFF' },
  heading: { fontSize: 18, fontWeight: '700', marginTop: 10, marginBottom: 6 },
  subHeading: { fontSize: 16 },
  hr: { borderTopWidth: 1, borderTopColor: '#ddd', marginVertical: 10 },
  codeBox: { backgroundColor: '#f6f8fa', borderRadius: 6, padding: 10, marginBottom: 8 },
  tableWrap: { marginBottom: 8 },
  table: { marginBottom: 8 },
  tableRow: { flexDirection: 'row', borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#ddd' },
  tableRowAlt: { backgroundColor: '#f2f4f7' },
  cell: { minWidth: 88, paddingHorizontal: 8, paddingVertical: 6, fontSize: 13 },
  th: { fontWeight: '700' },
  list: { marginBottom: 8 },
  listItem: { fontSize: 15, lineHeight: 22, marginBottom: 2 },
  listMarker: { color: '#666' },
});
