import { create } from 'zustand';
import { KEYS, loadJSON, removeKey, saveJSON } from '../lib/persist';

interface AppearanceState {
  backgroundUri: string | null;
  dim: number; // 0.1 - 0.75（对齐 iOS ChatAppearanceStore）
  hydrate: () => Promise<void>;
  setBackground: (uri: string) => void;
  clearBackground: () => void;
  setDim: (v: number) => void;
}

const DEFAULT_DIM = 0.35;

export const useAppearance = create<AppearanceState>((set) => ({
  backgroundUri: null,
  dim: DEFAULT_DIM,
  hydrate: async () => {
    const uri = await loadJSON<string | null>(KEYS.wallpaper, null);
    const dim = await loadJSON<number>(KEYS.bgDim, DEFAULT_DIM);
    set({ backgroundUri: uri, dim });
  },
  setBackground: (uri) => {
    set({ backgroundUri: uri });
    void saveJSON(KEYS.wallpaper, uri);
  },
  clearBackground: () => {
    set({ backgroundUri: null });
    void removeKey(KEYS.wallpaper);
  },
  setDim: (v) => {
    const clamped = Math.min(0.75, Math.max(0.1, Math.round(v * 100) / 100));
    set({ dim: clamped });
    void saveJSON(KEYS.bgDim, clamped);
  },
}));
