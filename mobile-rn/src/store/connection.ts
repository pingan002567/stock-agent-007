import { create } from 'zustand';
import { probeHealth } from '../api/client';
import { KEYS, loadJSON, saveJSON } from '../lib/persist';
import { clearProfile, loadProfile, saveProfile } from './token';
import type { HealthResponse } from '../types';

export function normalizeBaseURL(raw: string): string {
  let s = raw.trim();
  if (!s) throw new Error('请填写远端地址');
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
  while (s.endsWith('/')) s = s.slice(0, -1);
  return s;
}

/**
 * 快捷地址默认值：仓库里不硬编码服务器 IP（避免泄露），
 * 需要时通过 EXPO_PUBLIC_DEFAULT_BASE_URL / EXPO_PUBLIC_ALT_BASE_URL 注入。
 */
export const DEFAULT_BASE_URL = process.env.EXPO_PUBLIC_DEFAULT_BASE_URL ?? '';
export const ALT_BASE_URL = process.env.EXPO_PUBLIC_ALT_BASE_URL ?? '';

interface ConnectionState {
  baseURL: string;
  token: string;
  status: 'disconnected' | 'connecting' | 'connected';
  health: HealthResponse | null;
  error: string | null;
  lastSuccessfulUrl: string;
  authFailed: boolean;
  hydrate: () => Promise<void>;
  connect: (baseURL: string, token: string) => Promise<void>;
  reprobeHealth: () => Promise<string | null>;
  markAuthFailed: () => void;
  clearAuthFailure: () => void;
  disconnect: () => void;
}

export const useConnection = create<ConnectionState>((set, get) => ({
  baseURL: '',
  token: '',
  status: 'disconnected',
  health: null,
  error: null,
  lastSuccessfulUrl: '',
  authFailed: false,

  hydrate: async () => {
    const profile = await loadProfile();
    const last = await loadJSON<string>(KEYS.lastSuccessfulUrl, '');
    set({
      lastSuccessfulUrl: last,
      ...(profile ? { baseURL: profile.baseURL, token: profile.token } : {}),
    });
  },

  connect: async (baseURL, token) => {
    set({ status: 'connecting', error: null });
    try {
      const url = normalizeBaseURL(baseURL);
      const trimmedToken = token.trim();
      const health = await probeHealth(url, trimmedToken);
      if (health.status !== 'ok' || !health.agent_runtime) {
        throw new Error(trimmedToken ? '访问令牌无效（health 无 agent_runtime）' : '需要访问令牌');
      }
      await saveProfile(url, trimmedToken);
      await saveJSON(KEYS.lastSuccessfulUrl, url);
      set({
        baseURL: url,
        token: trimmedToken,
        status: 'connected',
        health,
        lastSuccessfulUrl: url,
        authFailed: false,
      });
    } catch (err) {
      set({ status: 'disconnected', error: err instanceof Error ? err.message : String(err) });
    }
  },

  /** 重新探测健康（对齐 iOS「重新探测健康」） */
  reprobeHealth: async () => {
    const { baseURL, token } = get();
    if (!baseURL) return '尚未连接';
    try {
      const health = await probeHealth(baseURL, token);
      set({ health });
      return health.status === 'ok' ? null : `状态异常：${health.status}`;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
      return msg;
    }
  },

  markAuthFailed: () => set({ authFailed: true }),

  clearAuthFailure: () => set({ authFailed: false }),

  disconnect: () => {
    void clearProfile();
    set({ status: 'disconnected', baseURL: '', token: '', health: null, error: null });
  },
}));
