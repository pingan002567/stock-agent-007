import { AppState } from 'react-native';
import * as BackgroundTask from 'expo-background-task';
import * as TaskManager from 'expo-task-manager';
import { fetchMessages, fetchMonitorEvents, fetchRunStatus } from '../api/client';
import { loadProfile } from '../store/token';
import {
  KEYS,
  loadJSON,
  loadNotifiedIds,
  loadPendingStreams,
  saveNotifiedIds,
  savePendingStreams,
  type PendingStream,
} from './persist';
import { showLocal } from './notify';
import type { BackendMessage, MonitorEvent } from '../types';

export const PUSH_TASK_NAME = 'stockagent-monitor-poll';

interface Profile {
  baseURL: string;
  token: string;
}

/** 只有 high/medium 才推，避免低频噪音 */
function shouldNotify(e: MonitorEvent): boolean {
  return String(e.severity ?? 'medium').toLowerCase() !== 'low';
}

function sevTitle(e: MonitorEvent): string {
  const sev = String(e.severity ?? '').toLowerCase();
  const prefix = sev === 'high' ? '🔴 高优先级' : '🟠 盯盘提醒';
  const sym = e.symbol ? `${e.symbol} ` : '';
  return `${prefix} · ${sym}${e.title ?? ''}`.trim();
}

function textOf(msg: BackendMessage): string {
  const p = (msg.payload as Record<string, unknown>) ?? {};
  for (const key of ['conclusion', 'text', 'content', 'message']) {
    const v = p[key];
    if (typeof v === 'string' && v.trim()) return v.replace(/\s+/g, ' ').slice(0, 140);
  }
  return '';
}

/** 盯盘事件：拉最新一页，和「已通知」比对后推送 */
async function checkMonitorEvents(profile: Profile): Promise<void> {
  const page = await fetchMonitorEvents(profile.baseURL, profile.token, 1, 20);
  const notified = new Set(await loadNotifiedIds());
  const fresh = page.items.filter((e) => !notified.has(e.event_id));
  if (fresh.length === 0) return;

  for (const e of fresh.filter(shouldNotify).slice(0, 3)) {
    await showLocal(sevTitle(e), String(e.message ?? '').slice(0, 160), {
      route: `stockagent://event/${e.event_id}`,
      eventId: e.event_id,
    });
  }
  // low 级别也标记，避免反复判定
  await saveNotifiedIds([...notified, ...fresh.map((e) => e.event_id)]);
}

/**
 * 会话回复完成：用持久化的 pendingStreams 探测 run 是否还活着。
 * 不删除条目（保留给前台恢复去重载历史），只打 notified 标记防重复通知。
 */
async function checkChatRuns(profile: Profile): Promise<void> {
  const pending = await loadPendingStreams();
  if (pending.length === 0) return;

  const next: PendingStream[] = [];
  for (const p of pending) {
    let alive = true;
    try {
      const st = await fetchRunStatus(profile.baseURL, profile.token, p.sessionId, p.runId);
      alive = st.alive !== false;
    } catch {
      next.push(p); // 探测失败：保留，下一轮再试
      continue;
    }

    if (alive) {
      next.push(p);
      continue;
    }

    if (!p.notified) {
      // App 在前台时用户自己能看见结果，不打扰；也不打标记，留给后台任务再通知
      if (AppState.currentState === 'active') {
        next.push(p);
        continue;
      }
      let body = '助手回复已完成，点开查看。';
      try {
        const page = await fetchMessages(profile.baseURL, profile.token, p.sessionId, { limitTurns: 2 });
        const assistant = [...page.items].reverse().find((m) => m.role !== 'user');
        const preview = assistant ? textOf(assistant) : '';
        if (preview) body = preview;
      } catch {
        /* 用默认文案 */
      }
      await showLocal('✅ 回复完成', body, {
        route: 'stockagent://chat',
        sessionId: p.sessionId,
      });
      next.push({ ...p, notified: true });
    } else {
      next.push(p);
    }
  }
  await savePendingStreams(next);
}

/**
 * 后台周期检查（Android 最短约 15 分钟）：盯盘事件 + 会话回复完成。
 */
async function runCheck(): Promise<BackgroundTask.BackgroundTaskResult> {
  try {
    const enabled = await loadJSON<boolean>(KEYS.pushEnabled, true);
    if (!enabled) return BackgroundTask.BackgroundTaskResult.Success;

    const profile = await loadProfile();
    if (!profile?.baseURL || !profile?.token) return BackgroundTask.BackgroundTaskResult.Success;

    const results = await Promise.allSettled([checkMonitorEvents(profile), checkChatRuns(profile)]);
    const failed = results.some((r) => r.status === 'rejected');
    return failed ? BackgroundTask.BackgroundTaskResult.Failed : BackgroundTask.BackgroundTaskResult.Success;
  } catch {
    return BackgroundTask.BackgroundTaskResult.Failed;
  }
}

// 必须在模块加载时定义（App 启动前）
TaskManager.defineTask(PUSH_TASK_NAME, runCheck);

export async function registerBackgroundPush(): Promise<boolean> {
  try {
    const already = await TaskManager.isTaskRegisteredAsync(PUSH_TASK_NAME);
    if (already) return true;
    await BackgroundTask.registerTaskAsync(PUSH_TASK_NAME, { minimumInterval: 15 });
    return true;
  } catch {
    return false;
  }
}

export async function unregisterBackgroundPush(): Promise<void> {
  try {
    if (await TaskManager.isTaskRegisteredAsync(PUSH_TASK_NAME)) {
      await BackgroundTask.unregisterTaskAsync(PUSH_TASK_NAME);
    }
  } catch {
    /* ignore */
  }
}

export async function isBackgroundPushRegistered(): Promise<boolean> {
  try {
    return await TaskManager.isTaskRegisteredAsync(PUSH_TASK_NAME);
  } catch {
    return false;
  }
}

/** 立即跑一次（用于「立即检查」按钮 / 前台轮询） */
export { runCheck as runPushCheckOnce };
