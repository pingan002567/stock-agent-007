import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';

const ACCENT_KEY = 'stockagent.themeAccentHex';
const SCHEME_KEY = 'stockagent.themeScheme';

export const ACCENT_PRESETS = [
  { id: 'brand', name: '柴犬棕', hex: '#5C4033' },
  { id: 'blue', name: '系统蓝', hex: '#007AFF' },
  { id: 'teal', name: '青绿', hex: '#0A7C6B' },
  { id: 'orange', name: '橙红', hex: '#E85D04' },
  { id: 'indigo', name: '靛蓝', hex: '#4F46E5' },
  { id: 'rose', name: '玫红', hex: '#E11D48' },
  { id: 'forest', name: '森林', hex: '#2F6B3A' },
  { id: 'slate', name: '石板', hex: '#475569' },
];

export type Scheme = 'system' | 'light' | 'dark';

interface ThemeState {
  accentHex: string;
  scheme: Scheme;
  hydrate: () => Promise<void>;
  setAccent: (hex: string) => void;
  setScheme: (s: Scheme) => void;
}

export const useTheme = create<ThemeState>((set) => ({
  accentHex: '#007AFF',
  scheme: 'system',
  hydrate: async () => {
    try {
      const [a, s] = await Promise.all([SecureStore.getItemAsync(ACCENT_KEY), SecureStore.getItemAsync(SCHEME_KEY)]);
      set({ accentHex: a || '#007AFF', scheme: (s as Scheme) || 'system' });
    } catch {
      /* ignore */
    }
  },
  setAccent: (hex) => {
    set({ accentHex: hex });
    void SecureStore.setItemAsync(ACCENT_KEY, hex);
  },
  setScheme: (s) => {
    set({ scheme: s });
    void SecureStore.setItemAsync(SCHEME_KEY, s);
  },
}));
