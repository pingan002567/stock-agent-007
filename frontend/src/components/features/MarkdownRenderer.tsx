import React, { useState } from "react";

/* ---------- inline formatting ---------- */

function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g);
  const out: React.ReactNode[] = [];
  let key = 0;

  for (const part of parts) {
    if (!part) continue;

    if (part.startsWith("**") && part.endsWith("**")) {
      out.push(<strong key={key++}>{part.slice(2, -2)}</strong>);
    } else if (part.startsWith("`") && part.endsWith("`")) {
      out.push(<code key={key++}>{part.slice(1, -1)}</code>);
    } else if (part.startsWith("[") && part.includes("](")) {
      const m = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (m) {
        out.push(<a key={key++} href={m[2]}>{m[1]}</a>);
      } else {
        out.push(<span key={key++}>{part}</span>);
      }
    } else {
      const lines = part.split("\n");
      lines.forEach((line, i) => {
        if (i > 0) out.push(<br key={`br-${key}`} />);
        out.push(<span key={key++}>{line}</span>);
      });
    }
  }

  return out;
}

/* ---------- block components ---------- */

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const body = code.replace(/```\w*\n?/, "").replace(/\n?```$/, "");
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(body);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* empty */ }
  };
  return (
    <div className="pre-wrap">
      <pre><code>{body}</code></pre>
      <button className="code-copy-btn" onClick={handleCopy}>{copied ? "已复制" : "复制"}</button>
    </div>
  );
}

function TableBlock({ text }: { text: string }) {
  const lines = text.trim().split("\n");
  const headers = lines[0].split("|").map((h) => h.trim()).filter(Boolean);
  const rows: string[][] = [];
  for (let i = 2; i < lines.length; i++) {
    const cells = lines[i].split("|").map((c) => c.trim()).filter(Boolean);
    if (cells.length) rows.push(cells);
  }
  return (
    <div className="msg-table-wrap">
      <table>
        {headers.length > 0 && (
          <thead>
            <tr>{headers.map((h, i) => <th key={i}>{renderInline(h)}</th>)}</tr>
          </thead>
        )}
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>{row.map((cell, ci) => <td key={ci}>{renderInline(cell)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ListBlock({ items, ordered }: { items: string[]; ordered: boolean }) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag>
      {items.map((item, i) => <li key={i}>{renderInline(item)}</li>)}
    </Tag>
  );
}

function ParagraphBlock({ text }: { text: string }) {
  return <p>{renderInline(text)}</p>;
}

/* ---------- line-group helpers ---------- */

interface ParsedBlock {
  type: "heading" | "ol" | "ul" | "table" | "hr" | "p";
  lines: string[];
}

function isTableSep(line: string): boolean {
  const stripped = line.replace(/\|/g, "").trim();
  return stripped.length > 0 && /^[\s:-]+$/.test(stripped);
}

/* ---------- main renderer ---------- */

interface MarkdownRendererProps {
  text: string;
}

export function MarkdownRenderer({ text }: MarkdownRendererProps) {
  // Extract code blocks first (they may contain markdown-like syntax inside)
  const outerParts = text.split(/(```[\s\S]*?```)/g);
  const elements: React.ReactNode[] = [];
  let key = 0;

  for (const part of outerParts) {
    if (!part.trim()) continue;

    // Code block — render verbatim
    if (part.startsWith("```")) {
      elements.push(<CodeBlock key={key++} code={part} />);
      continue;
    }

    // Non-code: parse line by line, grouping adjacent same-type lines
    const lines = part.split("\n");
    const blocks: ParsedBlock[] = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];
      const trimmed = line.trim();

      // skip pure-empty lines at block boundaries
      if (!trimmed) { i++; continue; }

      // heading (single line)
      const hMatch = trimmed.match(/^(#{1,4})\s+(.+)/);
      if (hMatch) {
        blocks.push({ type: "heading", lines: [hMatch[2]] });
        i++;
        continue;
      }

      // horizontal rule (single line)
      if (/^[-*_]{3,}$/.test(trimmed)) {
        blocks.push({ type: "hr", lines: [] });
        i++;
        continue;
      }

      // table: consecutive lines containing "|" or tab, with a separator line
      if ((trimmed.includes("|") || trimmed.includes("\t")) && i + 1 < lines.length && (lines[i + 1].includes("|") || lines[i + 1].includes("\t"))) {
        const tableLines: string[] = [trimmed];
        i++;
        while (i < lines.length && (lines[i].includes("|") || lines[i].includes("\t"))) {
          tableLines.push(lines[i].trim());
          i++;
        }
        // Only treat as table if a separator line exists
        if (tableLines.some((l) => isTableSep(l))) {
          blocks.push({ type: "table", lines: tableLines });
        } else {
          // Not a real table — join back as paragraph
          blocks.push({ type: "p", lines: [tableLines.join("\n")] });
        }
        continue;
      }

      // ordered list: consecutive numbered lines
      if (/^\d+\.\s/.test(trimmed)) {
        const items: string[] = [];
        while (i < lines.length) {
          const l = lines[i].trim();
          if (/^\d+\.\s/.test(l)) {
            items.push(l.replace(/^\d+\.\s/, ""));
            i++;
          } else if (!l) {
            // blank line inside list: check next non-blank line
            let j = i + 1;
            while (j < lines.length && !lines[j].trim()) j++;
            if (j < lines.length && /^\d+\.\s/.test(lines[j].trim())) {
              // next non-blank is also numbered — continue list (skip blanks)
              i = j;
            } else {
              break;
            }
          } else {
            break;
          }
        }
        blocks.push({ type: "ol", lines: items });
        continue;
      }

      // unordered list: consecutive bullet lines
      if (/^[-*+]\s/.test(trimmed)) {
        const items: string[] = [];
        while (i < lines.length) {
          const l = lines[i].trim();
          if (/^[-*+]\s/.test(l)) {
            items.push(l.replace(/^[-*+]\s/, ""));
            i++;
          } else if (!l) {
            let j = i + 1;
            while (j < lines.length && !lines[j].trim()) j++;
            if (j < lines.length && /^[-*+]\s/.test(lines[j].trim())) {
              i = j;
            } else {
              break;
            }
          } else {
            break;
          }
        }
        blocks.push({ type: "ul", lines: items });
        continue;
      }

      const paraLines: string[] = [];
      while (i < lines.length && lines[i].trim()) {
        const t = lines[i].trim();
        if (t.includes("|")) {
          let peek = i + 1;
          while (peek < lines.length && !lines[peek].trim()) peek++;
          if (peek < lines.length && lines[peek].trim().includes("|")) break;
        }
        if (/^(#{1,4}\s|\d+\.\s|[-*+]\s)/.test(t) || /^[-*_]{3,}$/.test(t)) break;
        paraLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: "p", lines: [paraLines.join("\n")] });
    }

    // Render collected blocks
    for (const block of blocks) {
      switch (block.type) {
        case "heading":
          elements.push(<h3 key={key++}>{renderInline(block.lines[0])}</h3>);
          break;
        case "hr":
          elements.push(<hr key={key++} />);
          break;
        case "table":
          elements.push(<TableBlock key={key++} text={block.lines.join("\n")} />);
          break;
        case "ol":
          elements.push(<ListBlock key={key++} items={block.lines} ordered={true} />);
          break;
        case "ul":
          elements.push(<ListBlock key={key++} items={block.lines} ordered={false} />);
          break;
        case "p":
        default:
          elements.push(<ParagraphBlock key={key++} text={block.lines[0]} />);
          break;
      }
    }
  }

  return <>{elements}</>;
}
