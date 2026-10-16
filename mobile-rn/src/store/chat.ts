import { AppState } from 'react-native';
import { create } from 'zustand';
import {
  cancelRun,
  createSession,
  deleteSession,
  fetchMessages,
  fetchRunStatus,
  fetchSessions,
  renameSession,
  sendMessage,
  streamURL,
} from '../api/client';
import { applyStreamUpdate, newAssistant, parseStreamEvent, type StreamUpdate } from '../api/parse';
import { streamSSE } from '../api/sse';
import { showLocal } from '../lib/notify';
import {
  KEYS,
  loadDrafts,
  loadPendingStreams,
  removeKey,
  saveDrafts,
  savePendingStreams,
  type PendingStream,
} from '../lib/persist';
import type { BackendMessage, CopilotSession, SessionUpload, Turn } from '../types';
import { useConnection } from './connection';

const MAX_RECONNECT = 5;
const IDLE_TIMEOUT_MS = 120_000;

interface SessionHistory {
  hasMore: boolean;
  nextBefore: string | null;
}

interface StreamCtl {
  controller: AbortController | null;
  watchdog: ReturnType<typeof setTimeout> | null;
  attempts: number;
  runId: string | null;
  turnId: string | null;
}

const streams: Record<string, StreamCtl> = {};

/** 心跳时间与 dock 计时器：用于「工作中 / 卡住」状态条（对齐 iOS 90s stuckIdleSeconds） */
const beats: Record<string, number> = {};
const dockTimers: Record<string, ReturnType<typeof setInterval>> = {};
const STUCK_IDLE_MS = 90_000;

function ctlOf(sessionId: string): StreamCtl {
  if (!streams[sessionId]) {
    streams[sessionId] = { controller: null, watchdog: null, attempts: 0, runId: null, turnId: null };
  }
  return streams[sessionId];
}

function cloneAssistant(a: NonNullable<Turn['assistant']>): NonNullable<Turn['assistant']> {
  return { ...a, tools: a.tools.map((t) => ({ ...t })), skillTrace: a.skillTrace.map((s) => ({ ...s })) };
}

interface ChatState {
  sessions: CopilotSession[];
  currentSessionId: string | null;
  turnsBySession: Record<string, Turn[]>;
  history: Record<string, SessionHistory>;
  drafts: Record<string, string>;
  activeStreams: Record<string, string>; // sessionId -> turnId（会话列表 spinner）
  docks: Record<string, 'working' | 'stuck'>;
  loadingSessions: boolean;
  loadingHistory: boolean;
  loadingMore: boolean;
  error: string | null;
  notice: string;

  hydrate: () => Promise<void>;
  loadSessions: () => Promise<void>;
  newSession: () => Promise<void>;
  openSession: (id: string) => Promise<void>;
  reloadSession: (id: string) => Promise<void>;
  renameSession: (id: string, title: string) => Promise<void>;
  removeSession: (id: string) => Promise<void>;
  loadEarlier: () => Promise<void>;
  send: (text: string, attachments?: SessionUpload[], humanInputResponse?: Record<string, unknown>, context?: { page?: string; symbol?: string }) => Promise<void>;
  replyClarification: (response: Record<string, unknown>) => Promise<void>;
  stop: (sessionId?: string) => void;
  retryTurn: (turnId: string) => Promise<void>;
  rememberDraft: (sessionId: string, text: string) => void;
  setError: (e: string | null) => void;
  clearNotice: () => void;
  recoverOnForeground: () => Promise<void>;
  reset: () => void;
}

export const useChat = create<ChatState>((set, get) => {
  function conn() {
    return useConnection.getState();
  }

  function turnsOf(sessionId: string): Turn[] {
    return get().turnsBySession[sessionId] ?? [];
  }

  function patchTurns(sessionId: string, updater: (turns: Turn[]) => Turn[]) {
    set((st) => ({
      turnsBySession: { ...st.turnsBySession, [sessionId]: updater(st.turnsBySession[sessionId] ?? []) },
    }));
  }

  function applyToTurn(sessionId: string, turnId: string, u: StreamUpdate) {
    patchTurns(sessionId, (turns) => {
      const idx = turns.findIndex((t) => t.id === turnId);
      if (idx < 0) return turns;
      const turn = turns[idx];
      const assistant = turn.assistant ? cloneAssistant(turn.assistant) : newAssistant();
      applyStreamUpdate(assistant, u);
      const next = turns.slice();
      next[idx] = { ...turn, assistant };
      return next;
    });
    if (u.kind === 'title') {
      set((st) => ({ sessions: st.sessions.map((s) => (s.session_id === sessionId ? { ...s, title: u.title } : s)) }));
    }
  }

  function startDock(sessionId: string) {
    beats[sessionId] = Date.now();
    if (dockTimers[sessionId]) clearInterval(dockTimers[sessionId]);
    set((st) => ({ docks: { ...st.docks, [sessionId]: 'working' } }));
    dockTimers[sessionId] = setInterval(() => {
      const idle = Date.now() - (beats[sessionId] ?? Date.now());
      set((st) => ({ docks: { ...st.docks, [sessionId]: idle > STUCK_IDLE_MS ? 'stuck' : 'working' } }));
    }, 5_000);
  }

  function stopDock(sessionId: string) {
    if (dockTimers[sessionId]) {
      clearInterval(dockTimers[sessionId]);
      delete dockTimers[sessionId];
    }
    set((st) => {
      const docks = { ...st.docks };
      delete docks[sessionId];
      return { docks };
    });
  }

  function armWatchdog(sessionId: string, runId: string, turnId: string) {
    const ctl = ctlOf(sessionId);
    if (ctl.watchdog) clearTimeout(ctl.watchdog);
    ctl.watchdog = setTimeout(() => void probeAndReconnect(sessionId, runId, turnId), IDLE_TIMEOUT_MS);
  }

  function clearWatchdog(sessionId: string) {
    const ctl = ctlOf(sessionId);
    if (ctl.watchdog) {
      clearTimeout(ctl.watchdog);
      ctl.watchdog = null;
    }
  }

  function finishStream(sessionId: string) {
    clearWatchdog(sessionId);
    stopDock(sessionId);
    const ctl = ctlOf(sessionId);
    ctl.controller = null;
    ctl.attempts = 0;
    ctl.runId = null;
    ctl.turnId = null;
    set((st) => {
      const active = { ...st.activeStreams };
      delete active[sessionId];
      return { activeStreams: active };
    });
    void clearPending(sessionId);
  }

  function failStream(sessionId: string, turnId: string | null, msg: string) {
    clearWatchdog(sessionId);
    stopDock(sessionId);
    const ctl = ctlOf(sessionId);
    ctl.controller = null;
    if (turnId) {
      patchTurns(sessionId, (turns) => {
        const idx = turns.findIndex((t) => t.id === turnId);
        if (idx < 0) return turns;
        const turn = turns[idx];
        const assistant = turn.assistant ? cloneAssistant(turn.assistant) : newAssistant();
        assistant.streaming = false;
        assistant.failed = true;
        assistant.phase = 'error';
        if (!assistant.answerText) assistant.answerText = msg;
        const next = turns.slice();
        next[idx] = { ...turn, assistant };
        return next;
      });
    }
    set((st) => {
      const active = { ...st.activeStreams };
      delete active[sessionId];
      return { activeStreams: active, error: msg };
    });
    void clearPending(sessionId);
  }

  /** 重连前先用 run-status 探测：已完成则改为重载历史，避免白白重放。 */
  async function probeAndReconnect(sessionId: string, runId: string, turnId: string) {
    const { baseURL, token } = conn();
    try {
      const st = await fetchRunStatus(baseURL, token, sessionId, runId);
      if (st.alive === false) {
        await get().reloadSession(sessionId);
        finishStream(sessionId);
        return;
      }
    } catch {
      /* 探测失败则继续尝试重连 */
    }
    reconnect(sessionId, runId, turnId);
  }

  function reconnect(sessionId: string, runId: string, turnId: string) {
    const ctl = ctlOf(sessionId);
    if (ctl.attempts >= MAX_RECONNECT) {
      failStream(sessionId, turnId, '连接多次失败，请重试');
      return;
    }
    ctl.attempts += 1;
    set({ notice: `连接中断，正在重连 (${ctl.attempts}/${MAX_RECONNECT})…` });
    const backoffMs = 400 * Math.min(8, Math.pow(2, ctl.attempts - 1));
    setTimeout(() => {
      if (ctlOf(sessionId).turnId !== turnId) return;
      // 重建当前轮次：清空 assistant，服务端会从 run 开头重放
      patchTurns(sessionId, (turns) => {
        const idx = turns.findIndex((t) => t.id === turnId);
        if (idx < 0) return turns;
        const assistant = newAssistant();
        assistant.streaming = true;
        const next = turns.slice();
        next[idx] = { ...turns[idx], assistant };
        return next;
      });
      void attemptStream(sessionId, runId, turnId);
    }, backoffMs);
  }

  async function attemptStream(sessionId: string, runId: string, turnId: string) {
    const { baseURL, token } = conn();
    const ctl = ctlOf(sessionId);
    const controller = new AbortController();
    ctl.controller = controller;
    armWatchdog(sessionId, runId, turnId);
    startDock(sessionId);

    let done = false;
    try {
      await streamSSE(streamURL(baseURL, token, sessionId, runId), {
        signal: controller.signal,
        onEvent: (ev) => {
          armWatchdog(sessionId, runId, turnId);
          beats[sessionId] = Date.now();
          const u = parseStreamEvent(ev);
          applyToTurn(sessionId, turnId, u);
          if (u.kind === 'final_answer' || u.kind === 'clarification' || u.kind === 'error') done = true;
        },
        onError: () => {},
        onDone: () => {},
      });
    } catch {
      /* abort 或网络异常 */
    }

    if (controller.signal.aborted) {
      finishStream(sessionId);
      return;
    }
    if (done) {
      finishStream(sessionId);
      set({ notice: '' });
      // App 不在前台时，用户看不到流式结果 → 补一条本地通知
      if (AppState.currentState !== 'active') {
        const turn = turnsOf(sessionId).find((t) => t.id === turnId);
        const answer = (turn?.assistant?.answerText ?? '').replace(/\s+/g, ' ').slice(0, 140);
        void showLocal('✅ 回复完成', answer || '助手回复已完成，点开查看。', {
          route: 'stockagent://chat',
          sessionId,
        }).catch(() => {});
      }
    } else {
      void probeAndReconnect(sessionId, runId, turnId);
    }
  }

  /* ---------- pending stream 持久化 ---------- */

  async function savePending(p: PendingStream) {
    const list = await loadPendingStreams();
    const existing = list.find((x) => x.sessionId === p.sessionId);
    const next = list.filter((x) => x.sessionId !== p.sessionId);
    // 保留后台任务写过的 notified 标记，避免重复推送
    next.push({ ...p, notified: existing?.notified });
    await savePendingStreams(next);
  }

  async function clearPending(sessionId: string) {
    const list = await loadPendingStreams();
    await savePendingStreams(list.filter((x) => x.sessionId !== sessionId));
  }

  return {
    sessions: [],
    currentSessionId: null,
    turnsBySession: {},
    history: {},
    drafts: {},
    activeStreams: {},
    docks: {},
    loadingSessions: false,
    loadingHistory: false,
    loadingMore: false,
    error: null,
    notice: '',

    hydrate: async () => {
      set({ drafts: await loadDrafts() });
    },

    loadSessions: async () => {
      const { baseURL, token } = conn();
      set({ loadingSessions: true });
      try {
        const sessions = await fetchSessions(baseURL, token);
        set({ sessions, error: null });
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        set({ loadingSessions: false });
      }
    },

    newSession: async () => {
      const { baseURL, token } = conn();
      try {
        const s = await createSession(baseURL, token);
        set((st) => ({
          sessions: [s, ...st.sessions.filter((x) => x.session_id !== s.session_id)],
          currentSessionId: s.session_id,
          turnsBySession: { ...st.turnsBySession, [s.session_id]: [] },
          error: null,
        }));
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      }
    },

    openSession: async (id) => {
      set({ currentSessionId: id, error: null });
      if (get().turnsBySession[id]) return; // 已有缓存，直接切换
      await get().reloadSession(id);
    },

    reloadSession: async (id) => {
      const { baseURL, token } = conn();
      set({ loadingHistory: true });
      try {
        const page = await fetchMessages(baseURL, token, id, { limitTurns: 20 });
        set((st) => ({
          turnsBySession: { ...st.turnsBySession, [id]: messagesToTurns(page.items) },
          history: { ...st.history, [id]: { hasMore: page.has_more, nextBefore: page.next_before } },
          error: null,
        }));
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        set({ loadingHistory: false });
      }
    },

    renameSession: async (id, title) => {
      const { baseURL, token } = conn();
      try {
        await renameSession(baseURL, token, id, title);
        set((st) => ({ sessions: st.sessions.map((s) => (s.session_id === id ? { ...s, title } : s)) }));
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      }
    },

    removeSession: async (id) => {
      const { baseURL, token } = conn();
      try {
        // 先停掉该会话的流，再删服务端
        ctlOf(id).controller?.abort();
        clearWatchdog(id);
        await deleteSession(baseURL, token, id);
        set((st) => {
          const sessions = st.sessions.filter((s) => s.session_id !== id);
          const turnsBySession = { ...st.turnsBySession };
          delete turnsBySession[id];
          const active = { ...st.activeStreams };
          delete active[id];
          return {
            sessions,
            turnsBySession,
            activeStreams: active,
            currentSessionId: st.currentSessionId === id ? null : st.currentSessionId,
          };
        });
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      }
    },

    loadEarlier: async () => {
      const { currentSessionId, history, loadingMore, loadingHistory } = get();
      if (!currentSessionId || loadingMore || loadingHistory) return;
      const h = history[currentSessionId];
      if (!h?.nextBefore) return;
      const { baseURL, token } = conn();
      set({ loadingMore: true });
      try {
        const page = await fetchMessages(baseURL, token, currentSessionId, { limitTurns: 20, before: h.nextBefore });
        patchTurns(currentSessionId, (turns) => [...messagesToTurns(page.items), ...turns]);
        set((st) => ({
          history: { ...st.history, [currentSessionId]: { hasMore: page.has_more, nextBefore: page.next_before } },
        }));
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        set({ loadingMore: false });
      }
    },

    send: async (text, attachments = [], humanInputResponse, context) => {
      let sessionId = get().currentSessionId;
      const { baseURL, token } = conn();
      if (!sessionId) {
        try {
          const s = await createSession(baseURL, token);
          sessionId = s.session_id;
          set((st) => ({
            sessions: [s, ...st.sessions.filter((x) => x.session_id !== s.session_id)],
            currentSessionId: s.session_id,
          }));
        } catch (e) {
          set({ error: e instanceof Error ? e.message : String(e) });
          return;
        }
      }

      const turnId = `rn-turn-${Date.now()}`;
      const userText = text || (humanInputResponse?.value as string) || '';
      const turn: Turn = { id: turnId, userText, assistant: newAssistant() };
      turn.assistant!.streaming = true;
      patchTurns(sessionId, (turns) => [...turns, turn]);
      set((st) => ({ activeStreams: { ...st.activeStreams, [sessionId]: turnId }, error: null, notice: '' }));

      try {
        const run = await sendMessage(baseURL, token, sessionId, text, attachments, humanInputResponse, context);
        const ctl = ctlOf(sessionId);
        ctl.runId = run.run_id;
        ctl.turnId = turnId;
        ctl.attempts = 0;
        await savePending({ sessionId, runId: run.run_id, turnId, userText, updatedAt: Date.now() });
        await attemptStream(sessionId, run.run_id, turnId);
      } catch (e) {
        failStream(sessionId, turnId, e instanceof Error ? e.message : String(e));
      }
    },

    replyClarification: async (response) => {
      const value = (response.value as string) ?? '';
      await get().send(value, [], response, { page: 'chat' });
    },

    stop: (sessionId) => {
      const sid = sessionId ?? get().currentSessionId;
      if (!sid) return;
      const ctl = ctlOf(sid);
      const { baseURL, token } = conn();
      ctl.controller?.abort();
      clearWatchdog(sid);
      if (ctl.runId) void cancelRun(baseURL, token, sid, ctl.runId).catch(() => {});
      finishStream(sid);
    },

    retryTurn: async (turnId) => {
      const sid = get().currentSessionId;
      if (!sid) return;
      const turn = turnsOf(sid).find((t) => t.id === turnId);
      if (!turn?.userText) return;
      await get().send(turn.userText);
    },

    rememberDraft: (sessionId, text) => {
      set((st) => {
        const drafts = { ...st.drafts, [sessionId]: text };
        void saveDrafts(drafts);
        return { drafts };
      });
    },

    setError: (e) => set({ error: e }),
    clearNotice: () => set({ notice: '' }),

    /** 前台恢复：刷新会话列表 + 处理断线遗留的流（探测 run 是否还活着）。 */
    recoverOnForeground: async () => {
      await get().loadSessions();
      const pending = await loadPendingStreams();
      for (const p of pending) {
        const ctl = ctlOf(p.sessionId);
        if (ctl.controller) continue; // 本地流还在，不重复
        const { baseURL, token } = conn();
        try {
          const st = await fetchRunStatus(baseURL, token, p.sessionId, p.runId);
          if (st.alive) {
            // 后台仍在跑 → 重挂
            ctl.runId = p.runId;
            ctl.turnId = p.turnId;
            ctl.attempts = 0;
            set((s) => ({ activeStreams: { ...s.activeStreams, [p.sessionId]: p.turnId } }));
            await attemptStream(p.sessionId, p.runId, p.turnId);
          } else {
            // 已结束 → 重载该会话历史
            await get().reloadSession(p.sessionId);
            await clearPending(p.sessionId);
          }
        } catch {
          await clearPending(p.sessionId);
        }
      }
    },

    reset: () => {
      for (const sid of Object.keys(streams)) {
        streams[sid].controller?.abort();
        clearWatchdog(sid);
      }
      set({
        sessions: [],
        currentSessionId: null,
        turnsBySession: {},
        history: {},
        activeStreams: {},
        error: null,
        notice: '',
      });
      void removeKey(KEYS.pendingStreams);
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
      return {
        kind: 'tool_call',
        callId: str('call_id') || `${str('tool') || 'tool'}-${Date.now()}`,
        name: str('tool', 'name') || 'tool',
      };
    case 'tool_result':
      return { kind: 'tool_result', callId: str('call_id'), preview: str('result_preview', 'text', 'output', 'result') };
    case 'final_answer':
      return { kind: 'final_answer', text: str('conclusion', 'text', 'content') };
    case 'clarification':
      return { kind: 'clarification', request: null, text: str('question', 'text') };
    case 'skill_trace': {
      const items = Array.isArray(p.items) ? (p.items as Record<string, unknown>[]) : [];
      return items.length ? { kind: 'skill_trace', steps: items } : { kind: 'ignore' };
    }
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
      turns.push({
        id: m.message_id ?? `u-${Date.now()}-${turns.length}`,
        userText: typeof text === 'string' ? text : '',
        assistant: null,
      });
    } else if (turns.length > 0) {
      const turn = turns[turns.length - 1];
      if (!turn.assistant) turn.assistant = newAssistant();
      applyStreamUpdate(turn.assistant, messageToUpdate(m));
    }
  }
  return turns;
}
