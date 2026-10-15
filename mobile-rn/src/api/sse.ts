import { fetch as expoFetch } from 'expo/fetch';

export interface SSEEvent {
  type: string;
  data: string;
}

export interface StreamCallbacks {
  onEvent: (event: SSEEvent) => void;
  onError?: (err: unknown) => void;
  onDone?: () => void;
  signal?: AbortSignal;
}

/**
 * 最小 SSE 客户端：用 expo/fetch（WinterCG 兼容、支持流式 body）读取并解析
 * `event:`/`data:` 帧。逻辑对齐 iOS 端 `SSEClient.swift`（逐行缓冲 + 空行 flush）。
 *
 * 注意：RN 内置 fetch 在 Android 上对流式 response.body 支持不可靠，
 * 故用 Expo 第一方的 expo/fetch；若仍不稳，回退 react-native-sse。
 * 后端每 15s 有 `ping`/`progress` 心跳，这里不设读取超时，空闲判空交给
 * 上层 120s 看门狗（M0 暂未接，后续补齐）。
 */
export async function streamSSE(url: string, cb: StreamCallbacks): Promise<void> {
  const res = await expoFetch(url, {
    headers: { Accept: 'text/event-stream', 'Cache-Control': 'no-cache' },
    signal: cb.signal,
  });

  if (!res.ok) {
    throw new Error(`SSE HTTP ${res.status}`);
  }
  if (!res.body) {
    throw new Error('当前运行时不支持流式响应');
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = 'message';
  const dataLines: string[] = [];

  const flush = () => {
    if (dataLines.length === 0) {
      eventType = 'message';
      return;
    }
    cb.onEvent({ type: eventType, data: dataLines.join('\n') });
    eventType = 'message';
    dataLines.length = 0;
  };

  const handleLine = (line: string) => {
    if (line.startsWith(':')) return;
    if (line === '') {
      flush();
      return;
    }
    if (line.startsWith('event:')) {
      eventType = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, idx).replace(/\r$/, '');
        buffer = buffer.slice(idx + 1);
        handleLine(line);
      }
    }
    flush();
    cb.onDone?.();
  } catch (err) {
    cb.onError?.(err);
    throw err;
  }
}
