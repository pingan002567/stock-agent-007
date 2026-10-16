import { create } from 'zustand';
import {
  isBackgroundPushRegistered,
  registerBackgroundPush,
  runPushCheckOnce,
  unregisterBackgroundPush,
} from '../lib/pushTask';
import { ensurePermission, getPermissionGranted, sendTestNotification } from '../lib/notify';
import { KEYS, loadJSON, saveJSON } from '../lib/persist';

interface PushState {
  enabled: boolean;
  granted: boolean;
  backgroundRegistered: boolean;
  lastCheckAt: number | null;
  busy: boolean;
  message: string;
  hydrate: () => Promise<void>;
  refreshStatus: () => Promise<void>;
  enable: () => Promise<void>;
  disable: () => Promise<void>;
  test: () => Promise<void>;
  checkNow: () => Promise<void>;
}

export const usePush = create<PushState>((set, get) => ({
  enabled: false,
  granted: false,
  backgroundRegistered: false,
  lastCheckAt: null,
  busy: false,
  message: '',

  hydrate: async () => {
    const enabled = await loadJSON<boolean>(KEYS.pushEnabled, false);
    set({ enabled });
    await get().refreshStatus();
  },

  refreshStatus: async () => {
    const [granted, backgroundRegistered] = await Promise.all([
      getPermissionGranted(),
      isBackgroundPushRegistered(),
    ]);
    set({ granted, backgroundRegistered });
  },

  enable: async () => {
    set({ busy: true, message: '' });
    try {
      const granted = await ensurePermission();
      if (!granted) {
        set({ message: '系统未授予通知权限，请在系统设置里开启' });
        return;
      }
      const ok = await registerBackgroundPush();
      await saveJSON(KEYS.pushEnabled, true);
      set({
        enabled: true,
        granted: true,
        backgroundRegistered: ok,
        message: ok ? '已开启后台检查（约 15 分钟一次）' : '本地通知已开启，后台任务注册失败',
      });
    } finally {
      set({ busy: false });
    }
  },

  disable: async () => {
    set({ busy: true });
    try {
      await unregisterBackgroundPush();
      await saveJSON(KEYS.pushEnabled, false);
      set({ enabled: false, backgroundRegistered: false, message: '已关闭推送' });
    } finally {
      set({ busy: false });
    }
  },

  test: async () => {
    set({ busy: true, message: '' });
    try {
      const ok = await sendTestNotification();
      set({ granted: ok, message: ok ? '测试通知已发送' : '没有通知权限，无法发送' });
    } finally {
      set({ busy: false });
    }
  },

  checkNow: async () => {
    set({ busy: true, message: '' });
    try {
      await runPushCheckOnce();
      set({ lastCheckAt: Date.now(), message: '已检查一次（有新事件才会通知）' });
    } finally {
      set({ busy: false });
    }
  },
}));
