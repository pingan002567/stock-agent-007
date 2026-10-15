/** sessionStorage pending copilot streams for refresh / reconnect recovery. */

export type PendingCopilotStream = {
  sessionId: string;
  runId: string;
  userText: string;
  updatedAt: number;
};

const KEY = "stockagent.pendingCopilotStreams";

function readAll(): PendingCopilotStream[] {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as PendingCopilotStream[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(items: PendingCopilotStream[]) {
  try {
    if (!items.length) {
      sessionStorage.removeItem(KEY);
      return;
    }
    sessionStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* quota / private mode */
  }
}

export function upsertPendingStream(item: PendingCopilotStream): void {
  const rest = readAll().filter((x) => x.sessionId !== item.sessionId);
  rest.push(item);
  writeAll(rest);
}

export function removePendingStream(sessionId: string): void {
  writeAll(readAll().filter((x) => x.sessionId !== sessionId));
}

export function listPendingStreams(): PendingCopilotStream[] {
  return readAll();
}
