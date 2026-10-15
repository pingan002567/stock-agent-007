import type { SSEEvent } from './sse';

export type StreamUpdate =
  | { kind: 'partial'; text: string }
  | { kind: 'final'; text: string }
  | { kind: 'ignore' };

/**
 * 事件归约（M0 只处理正文；完整 10 类事件见技术选型文档 4.3）。
 * 语义对齐 iOS `CopilotStreamParser`：type 双轨、payload 双轨。
 */
export function parseStreamEvent(event: SSEEvent): StreamUpdate {
  let obj: Record<string, unknown> | null = null;
  try {
    obj = JSON.parse(event.data) as Record<string, unknown>;
  } catch {
    return { kind: 'ignore' };
  }

  const type =
    event.type && event.type !== 'message'
      ? event.type
      : ((obj.type as string) ?? 'message');
  const payload = (obj.payload as Record<string, unknown>) ?? {};

  const pick = (...keys: string[]): string => {
    for (const k of keys) {
      const v = payload[k] ?? obj?.[k];
      if (typeof v === 'string' && v.length > 0) return v;
    }
    return '';
  };

  switch (type) {
    case 'partial_answer':
    case 'message': {
      const text = pick('text', 'content');
      return text ? { kind: 'partial', text } : { kind: 'ignore' };
    }
    case 'final':
      return { kind: 'final', text: pick('conclusion', 'text', 'content') };
    case 'error':
      return { kind: 'final', text: pick('message', 'error') || event.data };
    default:
      return { kind: 'ignore' };
  }
}
