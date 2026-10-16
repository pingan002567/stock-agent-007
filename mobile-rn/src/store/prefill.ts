import { create } from 'zustand';

// 跨 Tab 的「在对话中分析」预填：标的详情页写入，对话页消费后清空。
export const usePrefill = create<{ text: string; set: (t: string) => void; take: () => string }>((set, get) => ({
  text: '',
  set: (t) => set({ text: t }),
  take: () => {
    const t = get().text;
    set({ text: '' });
    return t;
  },
}));
