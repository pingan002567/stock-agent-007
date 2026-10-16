import AsyncStorage from '@react-native-async-storage/async-storage';

// 非敏感的本地持久化（密钥类仍走 expo-secure-store）。
export const KEYS = {
  pendingStreams: 'stockagent.pendingStreams',
  drafts: 'stockagent.drafts',
  seenEventIds: 'stockagent.monitor.seenEventIds',
  notifiedEventIds: 'stockagent.notifiedEventIds',
  pushEnabled: 'stockagent.pushEnabled',
  wallpaper: 'stockagent.chatBackground',
  bgDim: 'stockagent.chatBgDim',
  lastSuccessfulUrl: 'stockagent.lastSuccessfulUrl',
} as const;

const SEEN_CAP = 500;

export async function loadJSON<T>(key: string, fallback: T): Promise<T> {
  try {
    const raw = await AsyncStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export async function saveJSON(key: string, value: unknown): Promise<void> {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore */
  }
}

export async function removeKey(key: string): Promise<void> {
  try {
    await AsyncStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

/* ---------- 进行中的流式轮次（前台恢复 + 回复完成推送共用） ---------- */

export interface PendingStream {
  sessionId: string;
  runId: string;
  turnId: string;
  userText: string;
  updatedAt: number;
  /** 后台已就该轮发过「回复完成」通知，避免重复 */
  notified?: boolean;
}

export async function loadPendingStreams(): Promise<PendingStream[]> {
  return loadJSON<PendingStream[]>(KEYS.pendingStreams, []);
}

export async function savePendingStreams(list: PendingStream[]): Promise<void> {
  await saveJSON(KEYS.pendingStreams, list);
}

/* ---------- 盯盘已读（500 上限，对齐 iOS MonitorSeenStore） ---------- */

export async function loadSeenEventIds(): Promise<string[]> {
  return loadJSON<string[]>(KEYS.seenEventIds, []);
}

export async function saveSeenEventIds(ids: string[]): Promise<void> {
  await saveJSON(KEYS.seenEventIds, ids.slice(-SEEN_CAP));
}

/* ---------- 推送已通知（与「已读」分开：推送去重不应清掉 App 内未读角标） ---------- */

export async function loadNotifiedIds(): Promise<string[]> {
  return loadJSON<string[]>(KEYS.notifiedEventIds, []);
}

export async function saveNotifiedIds(ids: string[]): Promise<void> {
  // 只保留最近 300 条，避免无限增长
  await saveJSON(KEYS.notifiedEventIds, Array.from(new Set(ids)).slice(-300));
}

/* ---------- 每会话草稿 ---------- */

export type DraftMap = Record<string, string>;

export async function loadDrafts(): Promise<DraftMap> {
  return loadJSON<DraftMap>(KEYS.drafts, {});
}

export async function saveDrafts(map: DraftMap): Promise<void> {
  await saveJSON(KEYS.drafts, map);
}
