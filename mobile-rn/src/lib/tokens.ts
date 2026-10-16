import { useMemo } from 'react';
import { useColorScheme } from 'react-native';
import { useTheme } from '../store/theme';

export interface Tokens {
  accent: string;
  dark: boolean;
  bg: string;
  card: string;
  cardAlt: string;
  text: string;
  sub: string;
  border: string;
  danger: string;
  input: string;
  bubble: string;
}

/**
 * 主题令牌：把「主题色 + 明暗模式」下发到各页控件。
 * 之前各页把 #007AFF / #fff 写死在 StyleSheet 里，导致换主题色和深色模式都不生效。
 */
export function useTokens(): Tokens {
  const accent = useTheme((s) => s.accentHex);
  const scheme = useTheme((s) => s.scheme);
  const system = useColorScheme();
  const dark = scheme === 'dark' || (scheme === 'system' && system === 'dark');

  return useMemo(
    () => ({
      accent,
      dark,
      bg: dark ? '#000000' : '#ffffff',
      card: dark ? '#1C1C1E' : '#f6f8fa',
      cardAlt: dark ? '#2C2C2E' : '#eef4ff',
      text: dark ? '#FFFFFF' : '#111111',
      sub: dark ? '#98989E' : '#8E8E93',
      border: dark ? '#2C2C2E' : '#e5e5ea',
      danger: '#FF3B30',
      input: dark ? '#1C1C1E' : '#ffffff',
      bubble: dark ? '#0B3D91' : accent,
    }),
    [accent, dark]
  );
}

/** 把老代码里写死的调色板映射到令牌上 */
function colorMap(t: Tokens): Record<string, string> {
  return {
    '#fff': t.bg,
    '#ffffff': t.bg,
    '#f6f8fa': t.card,
    '#f7f8fa': t.card,
    '#f4f6f8': t.card,
    '#eef4ff': t.cardAlt,
    '#e8eef4': t.cardAlt,
    '#f2f4f7': t.cardAlt,
    '#007AFF': t.accent,
    '#111': t.text,
    '#111111': t.text,
    '#333': t.text,
    '#333333': t.text,
    '#444': t.text,
    '#555': t.sub,
    '#666': t.sub,
    '#667': t.sub,
    '#8E8E93': t.sub,
    '#999': t.sub,
    '#C7C7CC': t.sub,
    '#ddd': t.border,
    '#eee': t.border,
    '#ccc': t.border,
    '#e3e5e8': t.border,
    '#e5e5ea': t.border,
  };
}

/**
 * 在渲染时把 StyleSheet 里的固定颜色替换成主题令牌，
 * 这样主题色和深色模式能真正作用到每个控件（无需逐页重写样式）。
 */
export function useThemedStyles<T extends Record<string, unknown>>(styles: T): T {
  const t = useTokens();
  return useMemo(() => {
    const map = colorMap(t);
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(styles)) {
      if (value && typeof value === 'object') {
        const row: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
          if (typeof v !== 'string') {
            row[k] = v;
          } else if (map[v]) {
            row[k] = map[v];
          } else if (v.startsWith('#007AFF')) {
            // 带透明度的主题色（#007AFF15 等）也要跟着主题走
            row[k] = t.accent + v.slice(7);
          } else {
            row[k] = v;
          }
        }
        out[key] = row;
      } else {
        out[key] = value;
      }
    }
    return out as T;
  }, [styles, t]);
}
