import { create } from 'zustand';
import { probeHealth } from '../api/client';
import { clearProfile, loadProfile, saveProfile } from './token';
import type { HealthResponse } from '../types';

export function normalizeBaseURL(raw: string): string {
  let s = raw.trim();
  if (!s) throw new Error('请填写远端地址');
  if (!/^https?:\/\//i.test(s)) s = 'https://' + s;
  while (s.endsWith('/')) s = s.slice(0, -1);
  return s;
}

interface ConnectionState {
  baseURL: string;
  token: string;
  status: 'disconnected' | 'connecting' | 'connected';
  health: HealthResponse | null;
  error: string | null;
  hydrate: () => Promise<void>;
  connect: (baseURL: string, token: string) => Promise<void>;
  disconnect: () => void;
}

export const useConnection = create<ConnectionState>((set) => ({
  baseURL: '',
  token: '',
  status: 'disconnected',
  health: null,
  error: null,

  hydrate: async () => {
    const profile = await loadProfile();
    if (profile) set({ baseURL: profile.baseURL, token: profile.token });
  },

  connect: async (baseURL, token) => {
    set({ status: 'connecting', error: null });
    try {
      const url = normalizeBaseURL(baseURL);
      const trimmedToken = token.trim();
      const health = await probeHealth(url, trimmedToken);
      if (health.status !== 'ok' || !health.agent_runtime) {
        throw new Error(
          trimmedToken ? '访问令牌无效（health 无 agent_runtime）' : '需要访问令牌'
        );
      }
      await saveProfile(url, trimmedToken);
      set({ baseURL: url, token: trimmedToken, status: 'connected', health });
    } catch (err) {
      set({ status: 'disconnected', error: err instanceof Error ? err.message : String(err) });
    }
  },

  disconnect: () => {
    void clearProfile();
    set({ status: 'disconnected', baseURL: '', token: '', health: null, error: null });
  },
}));
