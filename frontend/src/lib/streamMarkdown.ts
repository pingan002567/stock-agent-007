/** 流式 Markdown：已闭合段落稳定，只重渲生长尾（借鉴 TeamClu StreamMarkdown）。 */

/** 尾段超过此长度时流式阶段跳过 Markdown，用纯文本减轻重解析 */
export const STREAM_TAIL_PLAIN_TEXT_THRESHOLD = 4000;

/**
 * 按段落边界（`\\n\\n`）切出已闭合块；未闭合的 code fence 内不切。
 */
export function splitStableBlocks(text: string): { stable: string[]; tail: string } {
  const segments = text.split("\n\n");
  if (segments.length === 1) return { stable: [], tail: text };

  const stable: string[] = [];
  let current = "";
  let openFences = 0;

  for (let i = 0; i < segments.length - 1; i++) {
    current = current ? `${current}\n\n${segments[i]}` : segments[i];
    // CommonMark：行首 ≤3 空格的 ``` / ~~~
    openFences += segments[i].match(/^ {0,3}(```|~~~)/gm)?.length ?? 0;
    if (openFences % 2 === 0) {
      stable.push(current);
      current = "";
      openFences = 0;
    }
  }

  const lastSegment = segments[segments.length - 1];
  const tail = current ? `${current}\n\n${lastSegment}` : lastSegment;
  return { stable, tail };
}
