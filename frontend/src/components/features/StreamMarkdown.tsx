import { memo, useDeferredValue, useMemo } from "react";
import { MarkdownRenderer } from "@/components/features/MarkdownRenderer";
import {
  STREAM_TAIL_PLAIN_TEXT_THRESHOLD,
  splitStableBlocks,
} from "@/lib/streamMarkdown";

const StableBlock = memo(function StableBlock({ content }: { content: string }) {
  return <MarkdownRenderer text={content} />;
});

/**
 * 流式友好 Markdown：闭合段落 memo，只重渲生长尾。
 * 尾段过长时用纯文本，避免每帧全量解析。
 */
export function StreamMarkdown({ text, streaming = true }: { text: string; streaming?: boolean }) {
  const deferredText = useDeferredValue(text);
  const source = streaming ? deferredText : text;
  const { stable, tail } = useMemo(() => splitStableBlocks(source), [source]);

  if (!streaming) {
    return <MarkdownRenderer text={text} />;
  }

  const usePlainTail = tail.length > STREAM_TAIL_PLAIN_TEXT_THRESHOLD;

  return (
    <div className="stream-markdown">
      {stable.map((block, i) => (
        <StableBlock key={i} content={block} />
      ))}
      {tail ? (
        usePlainTail ? (
          <div className="stream-markdown-tail plain">{tail}</div>
        ) : (
          <div className="stream-markdown-tail">
            <MarkdownRenderer text={tail} />
          </div>
        )
      ) : null}
    </div>
  );
}
