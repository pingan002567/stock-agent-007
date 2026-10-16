import { create } from 'zustand';

export interface AskContext {
  page?: string;
  symbol?: string;
}

interface PrefillState {
  text: string;
  context: AskContext | null;
  set: (t: string, context?: AskContext) => void;
  take: () => { text: string; context: AskContext | null };
}

// 跨 Tab 的「在对话中分析」预填：标的详情页写入（带 page/symbol 上下文），对话页消费后清空。
export const usePrefill = create<PrefillState>((set, get) => ({
  text: '',
  context: null,
  set: (t, context) => set({ text: t, context: context ?? null }),
  take: () => {
    const { text, context } = get();
    set({ text: '', context: null });
    return { text, context };
  },
}));
