import { create } from 'zustand';
import {
  cancelRun,
  createSession,
  deleteSession,
  fetchMessages,
  fetchSessions,
  renameSession,
  sendMessage,
  streamURL,
} from '../api/client';
import { applyStreamUpdate, newAssistant, parseStreamEvent, type StreamUpdate } from '../api/parse';
import { streamSSE } from '../api/sse';
import type { BackendMessage, CopilotSession, SessionUpload, Turn } from '../types';
import { useConnection } from './connection';

const MAX_RECONNECT = 5;
const IDLE_TIMEOUT_MS = 120_000;

/* ---------- 流生命周期（模块级，不进 zustand） ---------- */
const streamCtl = {
  controller: null as AbortController | null,
  watchdog: null as ReturnType<typeof setTimeout> | null,
  attempts: 0,
  sessionId: null as string | null,
  runId: null as string | null,
  turnId: null as string | null,
};

function cloneAssistant(a: NonNullable<Turn['assistant']>): NonNullable<Turn['assistant']> {
  return { ...a, tools: a.tools.map((t) => ({ ...t })), skillTrace: a.skillTrace.map((s) => ({ ...s })) };
}

interface ChatState {
  sessions: CopilotSession[];
  currentSessionId: string | null;
  turns: Turn[];
  hasMore: boolean;
  nextBefore: string | null;
  loadingSessions: boolean;
  loadingHistory: boolean;
  loadingMore: boolean;
  busy: boolean;
  error: string | null;

  loadSessions: () => Promise<void>;
  newSession: () => Promise<void>;
  openSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  removeSession: (id: string) => Promise<void>;
  loadEarlier: () => Promise<void>;
  send: (text: string, attachments?: SessionUpload[], humanInputResponse?: Record<string, unknown>) => Promise<void>;
  replyClarification: (response: Record<string, unknown>) => Promise<void>;
  stop: () => void;
  retryLast: () => Promise<void>;
  reset: () => void;
}

export const useChat = create<ChatState>((set, get) => {
  function conn() {
    return useConnection.getState();
  }

  function applyToTurn(sessionId: string, turnId: string, u: StreamUpdate) {
    const state = get();
    if (state.currentSessionId !== sessionId) return;
    const idx = state.turns.findIndex((t) => t.id === turnId);
    if (idx < 0) return;
    const turn = state.turns[idx];
    const assistant = turn.assistant ? cloneAssistant(turn.assistant) : newAssistant();
    applyStreamUpdate(assistant, u);
    const turns = state.turns.slice();
    turns[idx] = { ...turn, assistant };
    set({ turns });
    if (u.kind === 'title') {
      set({
        sessions: state.sessions.map((s) => (s.session_id === sessionId ? { ...s, title: u.title } : s)),
      });
    }
  }

  function armWatchdog(sessionId: string, runId: string, turnId: string) {
    if (streamCtl.watchdog) clearTimeout(streamCtl.watchdog);
    streamCtl.watchdog = setTimeout(() => {
      // 120s 无帧 → 判定超时，重连
      reconnect(sessionId, runId, turnId);
    }, IDLE_TIMEOUT_MS);
  }

  function clearWatchdog() {
    if (streamCtl.watchdog) {
      clearTimeout(streamCtl.watchdog);
      streamCtl.watchdog = null;
    }
  }

  function finishStream() {
    clearWatchdog();
    streamCtl.controller = null;
    streamCtl.attempts = 0;
    set({ busy: false });
  }

  function failStream(msg: string) {
    clearWatchdog();
    streamCtl.controller = null;
    const state = get();
    if (streamCtl.turnId) {
      const idx = state.turns.findIndex((t) => t.id === streamCtl.turnId);
      if (idx >= 0) {
        const turn = state.turns[idx];
        const assistant = turn.assistant ? cloneAssistant(turn.assistant) : newAssistant();
        assistant.streaming = false;
        assistant.failed = true;
        assistant.phase = 'error';
        if (!assistant.answerText) assistant.answerText = msg;
        const turns = state.turns.slice();
        turns[idx] = { ...turn, assistant };
        set({ turns });
      }
    }
    set({ busy: false, error: msg });
  }

  function reconnect(sessionId: string, runId: string, turnId: string) {
    if (streamCtl.attempts >= MAX_RECONNECT) {
      failStream('连接多次失败，请重试');
      return;
    }
    streamCtl.attempts += 1;
    const backoffMs = 400 * Math.min(8, Math.pow(2, streamCtl.attempts - 1));
    setTimeout(() => {
      // 重建当前轮次：清空 assistant，重放会从 run 开头再来一遍
      const state = get();
      if (streamCtl.turnId !== turnId) return;
      const idx = state.turns.findIndex((t) => t.id === turnId);
      if (idx >= 0) {
        const turn = state.turns[idx];
        const assistant = newAssistant();
        assistant.streaming = true;
        const turns = state.turns.slice();
        turns[idx] = { ...turn, assistant };
        set({ turns });
      }
      void attemptStream(sessionId, runId, turnId);
    }, backoffMs);
  }

  async function attemptStream(sessionId: string, runId: string, turnId: string) {
    const { baseURL, token } = conn();
    const controller = new AbortController();
    streamCtl.controller = controller;
    armWatchdog(sessionId, runId, turnId);

    let done = false;
    try {
      await streamSSE(streamURL(baseURL, token, sessionId, runId), {
        signal: controller.signal,
        onEvent: (ev) => {
          armWatchdog(sessionId, runId, turnId); // 任意帧（含 ping/progress）都算存活
          const u = parseStreamEvent(ev);
          applyToTurn(sessionId, turnId, u);
          if (u.kind === 'final_answer' || u.kind === 'clarification' || u.kind === 'error') done = true;
        },
        onError: () => {},
        onDone: () => {},
      });
    } catch {
      // streamSSE 抛错（abort 或网络异常）
    }

    if (controller.signal.aborted) {
      finishStream();
      return;
    }
    if (done) {
      finishStream();
    } else {
      reconnect(sessionId, runId, turnId);
    }
  }

  return {
    sessions: [],
    currentSessionId: null,
    turns: [],
    hasMore: false,
    nextBefore: null,
    loadingSessions: false,
    loadingHistory: false,
    loadingMore: false,
    busy: false,
    error: null,

    loadSessions: async () => {
      const { baseURL, token } = conn();
      set({ loadingSessions: true });
      try {
        const sessions = await fetchSessions(baseURL, token);
        set({ sessions });
      } finally {
        set({ loadingSessions: false });
      }
    },

    newSession: async () => {
      const { baseURL, token } = conn();
      const s = await createSession(baseURL, token);
      set((st) => ({
        sessions: [s, ...st.sessions.filter((x) => x.session_id !== s.session_id)],
        currentSessionId: s.session_id,
        turns: [],
        hasMore: false,
        nextBefore: null,
        error: null,
      }));
    },

    openSession: async (id) => {
      const { baseURL, token } = conn();
      set({ currentSessionId: id, turns: [], hasMore: false, nextBefore: null, loadingHistory: true, error: null });
      try {
        const page = await fetchMessages(baseURL, token, id, { limitTurns: 20 });
        set({
          turns: messagesToTurns(page.items),
          hasMore: page.has_more,
          nextBefore: page.next_before,
        });
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        set({ loadingHistory: false });
      }
    },

    renameSession: async (id, title) => {
      const { baseURL, token } = conn();
      await renameSession(baseURL, token, id, title);
      set((st) => ({ sessions: st.sessions.map((s) => (s.session_id === id ? { ...s, title } : s)) }));
    },

    removeSession: async (id) => {
      const { baseURL, token } = conn();
      await deleteSession(baseURL, token, id);
      set((st) => {
        const sessions = st.sessions.filter((s) => s.session_id !== id);
        return {
          sessions,
          currentSessionId: st.currentSessionId === id ? null : st.currentSessionId,
          turns: st.currentSessionId === id ? [] : st.turns,
        };
      });
    },

    loadEarlier: async () => {
      const { currentSessionId, nextBefore, busy } = get();
      if (!currentSessionId || busy || !nextBefore) return;
      const { baseURL, token } = conn();
      set({ loadingMore: true });
      try {
        const page = await fetchMessages(baseURL, token, currentSessionId, { limitTurns: 20, before: nextBefore });
        set((st) => ({
          turns: [...messagesToTurns(page.items), ...st.turns],
          hasMore: page.has_more,
          nextBefore: page.next_before,
        }));
      } finally {
        set({ loadingMore: false });
      }
    },

    send: async (text, attachments = [], humanInputResponse) => {
      let sessionId = get().currentSessionId;
      const { baseURL, token } = conn();
      if (!sessionId) {
        const s = await createSession(baseURL, token);
        sessionId = s.session_id;
        set((st) => ({
          sessions: [s, ...st.sessions.filter((x) => x.session_id !== s.session_id)],
          currentSessionId: s.session_id,
        }));
      }

      const turnId = `rn-turn-${Date.now()}`;
      const userText = text || (humanInputResponse?.value as string) || '';
      const turn: Turn = { id: turnId, userText, assistant: newAssistant() };
      turn.assistant!.streaming = true;
      set((st) => ({ turns: [...st.turns, turn], busy: true, error: null }));

      try {
        const run = await sendMessage(baseURL, token, sessionId, text, attachments, humanInputResponse);
        streamCtl.sessionId = sessionId;
        streamCtl.runId = run.run_id;
        streamCtl.turnId = turnId;
        streamCtl.attempts = 0;
        await attemptStream(sessionId, run.run_id, turnId);
      } catch (e) {
        failStream(e instanceof Error ? e.message : String(e));
      }
    },

    replyClarification: async (response) => {
      const value = (response.value as string) ?? '';
      await get().send(value, [], response);
    },

    stop: () => {
      const ctl = streamCtl;
      const { baseURL, token } = conn();
      const currentSessionId = get().currentSessionId;
      ctl.controller?.abort();
      clearWatchdog();
      if (currentSessionId && ctl.runId) {
        void cancelRun(baseURL, token, currentSessionId, ctl.runId).catch(() => {});
      }
      ctl.attempts = 0;
      set({ busy: false });
    },

    retryLast: async () => {
      const last = get().turns[get().turns.length - 1];
      if (!last) return;
      await get().send(last.userText);
    },

    reset: () => {
      finishStream();
      set({ sessions: [], currentSessionId: null, turns: [], hasMore: false, nextBefore: null, busy: false, error: null });
    },
  };
});

/* ---------- 历史消息 → 轮次 ---------- */

function messageToUpdate(msg: BackendMessage): StreamUpdate {
  const p = (msg.payload as Record<string, unknown>) ?? {};
  const str = (...keys: string[]): string => {
    for (const k of keys) {
      const v = p[k];
      if (typeof v === 'string' && v.length > 0) return v;
    }
    return '';
  };
  switch (msg.kind) {
    case 'reasoning':
      return str('text', 'latest_text') ? { kind: 'reasoning', text: str('text', 'latest_text') } : { kind: 'ignore' };
    case 'tool_call':
      return { kind: 'tool_call', callId: str('call_id') || `${str('tool') || 'tool'}-${Date.now()}`, name: str('tool', 'name') || 'tool' };
    case 'tool_result':
      return { kind: 'tool_result', callId: str('call_id'), preview: str('result_preview', 'text', 'output', 'result') };
    case 'final_answer':
      return { kind: 'final_answer', text: str('conclusion', 'text', 'content') };
    case 'clarification':
      return { kind: 'clarification', request: null, text: str('question', 'text') };
    case 'error':
      return { kind: 'error', message: str('message', 'error') || '生成失败' };
    default:
      return { kind: 'ignore' };
  }
}

function messagesToTurns(messages: BackendMessage[]): Turn[] {
  const turns: Turn[] = [];
  for (const m of messages) {
    if (m.role === 'user') {
      const text = (m.payload as Record<string, unknown> | undefined)?.message;
      turns.push({ id: m.message_id ?? `u-${Date.now()}-${turns.length}`, userText: typeof text === 'string' ? text : '', assistant: null });
    } else if (turns.length > 0) {
      const turn = turns[turns.length - 1];
      if (!turn.assistant) turn.assistant = newAssistant();
      applyStreamUpdate(turn.assistant, messageToUpdate(m));
    }
  }
  return turns;
}
