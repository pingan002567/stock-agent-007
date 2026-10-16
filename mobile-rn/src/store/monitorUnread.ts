import { create } from 'zustand';
import { loadSeenEventIds, saveSeenEventIds } from '../lib/persist';

const SEEN_CAP = 500;

interface MonitorUnreadState {
  seen: string[];
  unreadCount: number;
  hydrate: () => Promise<void>;
  refreshFromEventIds: (ids: string[]) => void;
  markAllRead: (ids: string[]) => void;
  isUnread: (id: string) => boolean;
}

/** 盯盘未读（对齐 iOS MonitorSeenStore + MonitorUnreadStore） */
export const useMonitorUnread = create<MonitorUnreadState>((set, get) => ({
  seen: [],
  unreadCount: 0,
  hydrate: async () => {
    set({ seen: await loadSeenEventIds() });
  },
  refreshFromEventIds: (ids) => {
    const seen = new Set(get().seen);
    set({ unreadCount: ids.filter((id) => !seen.has(id)).length });
  },
  markAllRead: (ids) => {
    const merged = Array.from(new Set([...get().seen, ...ids])).slice(-SEEN_CAP);
    set({ seen: merged, unreadCount: 0 });
    void saveSeenEventIds(merged);
  },
  isUnread: (id) => !get().seen.includes(id),
}));
