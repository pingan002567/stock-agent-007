// 移植自 Web 端 frontend/src/lib/streamMarkdown.ts 与 MarkdownRenderer.tsx。
// 纯逻辑、无渲染依赖，便于两端共享与测试。

export const STREAM_TAIL_PLAIN_TEXT_THRESHOLD = 4000;

/** 按段落边界（`\n\n`）切出已闭合块；未闭合的 code fence 内不切。 */
export function splitStableBlocks(text: string): { stable: string[]; tail: string } {
  const segments = text.split('\n\n');
  if (segments.length === 1) return { stable: [], tail: text };

  const stable: string[] = [];
  let current = '';
  let openFences = 0;

  for (let i = 0; i < segments.length - 1; i++) {
    current = current ? `${current}\n\n${segments[i]}` : segments[i];
    openFences += segments[i].match(/^ {0,3}(```|~~~)/gm)?.length ?? 0;
    if (openFences % 2 === 0) {
      stable.push(current);
      current = '';
      openFences = 0;
    }
  }

  const lastSegment = segments[segments.length - 1];
  const tail = current ? `${current}\n\n${lastSegment}` : lastSegment;
  return { stable, tail };
}

export type MdBlock =
  | { type: 'code'; code: string }
  | { type: 'heading'; level: number; text: string }
  | { type: 'hr' }
  | { type: 'table'; headers: string[]; rows: string[][] }
  | { type: 'ol' | 'ul'; items: string[] }
  | { type: 'p'; text: string };

export type InlineSegment =
  | { kind: 'text'; text: string }
  | { kind: 'bold'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'link'; text: string; url: string };

function isTableSep(line: string): boolean {
  const stripped = line.replace(/\|/g, '').trim();
  return stripped.length > 0 && /^[\s:-]+$/.test(stripped);
}

function isBullet(line: string): boolean {
  return /^[-*+]\s/.test(line);
}

function isOrdered(line: string): boolean {
  return /^\d+\.\s/.test(line);
}

/** 先抽代码块（内部可能含类 Markdown 语法），再逐行归组为块。 */
export function parseMarkdownBlocks(text: string): MdBlock[] {
  const outerParts = text.split(/(```[\s\S]*?```)/g);
  const blocks: MdBlock[] = [];

  for (const part of outerParts) {
    if (!part.trim()) continue;
    if (part.startsWith('```')) {
      const body = part.replace(/```\w*\n?/, '').replace(/\n?```$/, '');
      blocks.push({ type: 'code', code: body });
      continue;
    }

    const lines = part.split('\n');
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();
      if (!trimmed) {
        i++;
        continue;
      }

      const h = trimmed.match(/^(#{1,4})\s+(.+)/);
      if (h) {
        blocks.push({ type: 'heading', level: h[1].length, text: h[2] });
        i++;
        continue;
      }
      if (/^[-*_]{3,}$/.test(trimmed)) {
        blocks.push({ type: 'hr' });
        i++;
        continue;
      }

      if (
        (trimmed.includes('|') || trimmed.includes('\t')) &&
        i + 1 < lines.length &&
        (lines[i + 1].includes('|') || lines[i + 1].includes('\t'))
      ) {
        const tableLines: string[] = [trimmed];
        i++;
        while (i < lines.length && (lines[i].includes('|') || lines[i].includes('\t'))) {
          tableLines.push(lines[i].trim());
          i++;
        }
        if (tableLines.some(isTableSep)) {
          const headers = tableLines[0]
            .split('|')
            .map((s) => s.trim())
            .filter(Boolean);
          const rows: string[][] = [];
          for (let r = 2; r < tableLines.length; r++) {
            const cells = tableLines[r]
              .split('|')
              .map((s) => s.trim())
              .filter(Boolean);
            if (cells.length) rows.push(cells);
          }
          blocks.push({ type: 'table', headers, rows });
        } else {
          blocks.push({ type: 'p', text: tableLines.join('\n') });
        }
        continue;
      }

      if (isOrdered(trimmed)) {
        const items: string[] = [];
        while (i < lines.length) {
          const l = lines[i].trim();
          if (isOrdered(l)) {
            items.push(l.replace(/^\d+\.\s/, ''));
            i++;
          } else if (!l) {
            let j = i + 1;
            while (j < lines.length && !lines[j].trim()) j++;
            if (j < lines.length && isOrdered(lines[j].trim())) i = j;
            else break;
          } else {
            break;
          }
        }
        blocks.push({ type: 'ol', items });
        continue;
      }

      if (isBullet(trimmed)) {
        const items: string[] = [];
        while (i < lines.length) {
          const l = lines[i].trim();
          if (isBullet(l)) {
            items.push(l.replace(/^[-*+]\s/, ''));
            i++;
          } else if (!l) {
            let j = i + 1;
            while (j < lines.length && !lines[j].trim()) j++;
            if (j < lines.length && isBullet(lines[j].trim())) i = j;
            else break;
          } else {
            break;
          }
        }
        blocks.push({ type: 'ul', items });
        continue;
      }

      const paraLines: string[] = [];
      while (i < lines.length && lines[i].trim()) {
        const t = lines[i].trim();
        if (t.includes('|')) {
          let peek = i + 1;
          while (peek < lines.length && !lines[peek].trim()) peek++;
          if (peek < lines.length && lines[peek].trim().includes('|')) break;
        }
        if (/^(#{1,4}\s|\d+\.\s|[-*+]\s)/.test(t) || /^[-*_]{3,}$/.test(t)) break;
        paraLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'p', text: paraLines.join('\n') });
    }
  }

  return blocks;
}

/** 行内：**加粗**、`代码`、[链接](url)。 */
export function parseInline(text: string): InlineSegment[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g);
  const out: InlineSegment[] = [];
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith('**') && part.endsWith('**')) {
      out.push({ kind: 'bold', text: part.slice(2, -2) });
    } else if (part.startsWith('`') && part.endsWith('`')) {
      out.push({ kind: 'code', text: part.slice(1, -1) });
    } else if (part.startsWith('[') && part.includes('](')) {
      const m = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (m) out.push({ kind: 'link', text: m[1], url: m[2] });
      else out.push({ kind: 'text', text: part });
    } else {
      out.push({ kind: 'text', text: part });
    }
  }
  return out;
}
